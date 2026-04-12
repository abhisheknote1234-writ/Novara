"""
data_pipeline.py — Standalone Physiological Signal Processing
===============================================================
Simplified, self-contained algorithms for:
  - Heart rate from R-peak detection
  - HRV (RMSSD, SDNN)
  - Stress score (autonomic balance estimate)
  - Recovery score (parasympathetic reactivation)

These are simplified standalone implementations.
No dependency on MaternalGuard modules.
"""
import numpy as np
from scipy.signal import butter, filtfilt, find_peaks
from typing import Dict, Optional, Tuple


class PhysioPipeline:
    """
    Standalone signal processing pipeline.
    Accepts raw ECG/PPG signals and computes clinical metrics.
    """

    def __init__(self, fs: int = 250):
        self.fs = fs

    # ─── PUBLIC API ──────────────────────────────────────────────

    def ingest(
        self, ecg_signal: np.ndarray, ppg_signal: Optional[np.ndarray] = None
    ) -> Dict[str, float]:
        """
        Process raw physiological signals and return computed metrics.

        Args:
            ecg_signal: 1-D array of raw ECG samples
            ppg_signal: 1-D array of raw PPG samples (optional)

        Returns:
            Dict with keys: heart_rate, hrv_rmssd, hrv_sdnn, stress_score,
                            recovery_score, signal_quality, n_beats
        """
        # Step 1: Filter ECG
        ecg_filtered = self._bandpass_ecg(ecg_signal)

        # Step 2: Detect R-peaks
        r_peaks = self._detect_r_peaks(ecg_filtered)

        if len(r_peaks) < 3:
            return self._empty_result()

        # Step 3: Compute RR intervals
        rr_intervals_ms = np.diff(r_peaks) / self.fs * 1000.0

        # Step 4: Clean RR intervals (reject physiologically impossible)
        rr_clean = self._clean_rr(rr_intervals_ms)

        if len(rr_clean) < 2:
            return self._empty_result()

        # Step 5: Compute metrics
        heart_rate   = 60000.0 / np.mean(rr_clean)
        hrv_rmssd    = self._compute_rmssd(rr_clean)
        hrv_sdnn     = np.std(rr_clean, ddof=1)
        stress_score = self._compute_stress(heart_rate, hrv_rmssd, hrv_sdnn)
        recovery     = self._compute_recovery(hrv_rmssd, heart_rate)
        sqi          = self._signal_quality(ecg_filtered, r_peaks)

        return {
            "heart_rate":     round(heart_rate, 1),
            "hrv_rmssd":      round(hrv_rmssd, 2),
            "hrv_sdnn":       round(hrv_sdnn, 2),
            "stress_score":   round(stress_score, 1),
            "recovery_score": round(recovery, 1),
            "signal_quality": round(sqi, 3),
            "n_beats":        len(r_peaks),
        }

    def compute_daily_summary(
        self, ecg_segments: list, ppg_segments: Optional[list] = None
    ) -> Dict[str, float]:
        """
        Aggregate multiple signal segments into a daily summary.
        Each segment is processed independently, then metrics are averaged.
        """
        results = []
        for i, ecg_seg in enumerate(ecg_segments):
            ppg_seg = ppg_segments[i] if ppg_segments and i < len(ppg_segments) else None
            r = self.ingest(ecg_seg, ppg_seg)
            if r["n_beats"] > 0:
                results.append(r)

        if not results:
            return self._empty_result()

        hrs = [r["heart_rate"] for r in results]
        return {
            "avg_heart_rate":     round(np.mean(hrs), 1),
            "avg_hrv_rmssd":      round(np.mean([r["hrv_rmssd"] for r in results]), 2),
            "avg_hrv_sdnn":       round(np.mean([r["hrv_sdnn"] for r in results]), 2),
            "avg_stress_score":   round(np.mean([r["stress_score"] for r in results]), 1),
            "avg_recovery_score": round(np.mean([r["recovery_score"] for r in results]), 1),
            "min_heart_rate":     round(min(hrs), 1),
            "max_heart_rate":     round(max(hrs), 1),
            "total_samples":      sum(len(seg) for seg in ecg_segments),
        }

    # ─── ECG FILTERING ───────────────────────────────────────────

    def _bandpass_ecg(self, ecg: np.ndarray) -> np.ndarray:
        """Bandpass filter ECG: 0.5–40 Hz, 4th order Butterworth."""
        if len(ecg) < 50:
            return ecg
        nyq = self.fs / 2.0
        low  = max(0.5 / nyq, 0.001)
        high = min(40.0 / nyq, 0.999)
        b, a = butter(4, [low, high], btype="band")
        try:
            return filtfilt(b, a, ecg.astype(np.float64))
        except Exception:
            return ecg.astype(np.float64)

    # ─── R-PEAK DETECTION (Simplified Pan-Tompkins) ──────────────

    def _detect_r_peaks(self, ecg_bp: np.ndarray) -> np.ndarray:
        """
        Simplified R-peak detection using differentiation + squaring
        + moving window integration + adaptive thresholding.
        """
        if len(ecg_bp) < self.fs:
            return np.array([], dtype=int)

        # Differentiation
        diff = np.diff(ecg_bp)

        # Squaring
        squared = diff ** 2

        # Moving window integration
        win_size = int(0.12 * self.fs)
        kernel = np.ones(win_size) / win_size
        mwi = np.convolve(squared, kernel, mode="same")

        # Kill edge effects
        mwi[:win_size] = 0
        mwi[-win_size:] = 0

        # Adaptive threshold
        threshold = np.mean(mwi) + 1.2 * np.std(mwi)
        min_dist  = int(0.3 * self.fs)  # 300ms minimum RR

        peaks, _ = find_peaks(mwi, height=threshold, distance=min_dist)

        # Refine: find true maximum in raw ECG near each detected peak
        refined = []
        for p in peaks:
            start = max(0, p - 12)
            end   = min(len(ecg_bp), p + 12)
            if start < end:
                refined.append(start + np.argmax(ecg_bp[start:end]))

        return np.array(refined, dtype=int)

    # ─── RR INTERVAL CLEANING ────────────────────────────────────

    def _clean_rr(self, rr_ms: np.ndarray) -> np.ndarray:
        """
        Remove physiologically impossible RR intervals.
        Valid range: 300–2000ms (30–200 bpm).
        Also reject intervals that deviate >50% from local median.
        """
        # Physiological bounds
        mask = (rr_ms > 300) & (rr_ms < 2000)
        rr_clean = rr_ms[mask]

        if len(rr_clean) < 3:
            return rr_clean

        # Reject outliers relative to local median
        median_rr = np.median(rr_clean)
        mask2 = np.abs(rr_clean - median_rr) < (0.5 * median_rr)
        return rr_clean[mask2]

    # ─── HRV COMPUTATION ─────────────────────────────────────────

    def _compute_rmssd(self, rr_ms: np.ndarray) -> float:
        """Root Mean Square of Successive Differences."""
        if len(rr_ms) < 2:
            return 0.0
        diffs = np.diff(rr_ms)
        return float(np.sqrt(np.mean(diffs ** 2)))

    # ─── STRESS SCORE ────────────────────────────────────────────

    def _compute_stress(self, hr: float, rmssd: float, sdnn: float) -> float:
        """
        Simplified stress score (0–100).
        
        Physiological rationale:
        - Higher HR → higher sympathetic activation → more stress
        - Lower RMSSD → less vagal tone → more stress
        - Lower SDNN → less overall variability → more stress
        
        This is NOT a clinical measurement — it's a risk-pattern indicator.
        """
        # HR component: score increases as HR rises above 70 bpm
        hr_score = np.clip((hr - 60) / 60.0, 0, 1)  # 0 at 60bpm, 1 at 120bpm

        # RMSSD component: score increases as RMSSD drops below 40ms
        rmssd_score = np.clip(1.0 - (rmssd / 60.0), 0, 1)  # 0 at 60ms, 1 at 0ms

        # SDNN component: score increases as SDNN drops below 50ms
        sdnn_score = np.clip(1.0 - (sdnn / 80.0), 0, 1)

        # Weighted combination
        raw = 0.35 * hr_score + 0.40 * rmssd_score + 0.25 * sdnn_score
        return round(raw * 100.0, 1)

    # ─── RECOVERY SCORE ──────────────────────────────────────────

    def _compute_recovery(self, rmssd: float, hr: float) -> float:
        """
        Simplified recovery score (0–100).
        Higher RMSSD + lower HR = better recovery (parasympathetic dominance).
        """
        # RMSSD contribution (higher = better recovery)
        rmssd_contrib = np.clip(rmssd / 80.0, 0, 1)

        # HR contribution (lower = better recovery)
        hr_contrib = np.clip(1.0 - (hr - 50) / 80.0, 0, 1)

        raw = 0.65 * rmssd_contrib + 0.35 * hr_contrib
        return round(raw * 100.0, 1)

    # ─── SIGNAL QUALITY ──────────────────────────────────────────

    def _signal_quality(self, ecg_bp: np.ndarray, peaks: np.ndarray) -> float:
        """
        Simple signal quality index (0–1).
        Based on peak regularity and amplitude consistency.
        """
        if len(peaks) < 3:
            return 0.0

        rr = np.diff(peaks) / self.fs * 1000.0
        rr_cv = np.std(rr) / np.mean(rr) if np.mean(rr) > 0 else 1.0

        # Lower CV = more regular = better quality
        regularity = np.clip(1.0 - rr_cv, 0, 1)

        # Amplitude consistency
        amps = [ecg_bp[p] for p in peaks if 0 <= p < len(ecg_bp)]
        if len(amps) > 1:
            amp_cv = np.std(amps) / (np.mean(np.abs(amps)) + 1e-9)
            amp_quality = np.clip(1.0 - amp_cv, 0, 1)
        else:
            amp_quality = 0.5

        return float(0.6 * regularity + 0.4 * amp_quality)

    # ─── HELPERS ─────────────────────────────────────────────────

    def _empty_result(self) -> Dict[str, float]:
        return {
            "heart_rate":     0.0,
            "hrv_rmssd":      0.0,
            "hrv_sdnn":       0.0,
            "stress_score":   0.0,
            "recovery_score": 0.0,
            "signal_quality": 0.0,
            "n_beats":        0,
        }
