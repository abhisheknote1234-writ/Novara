"""
=============================================================================
Research-Grade Real-Time PPG Peak Detection & Validation System  (v3)
=============================================================================

Foundational Signal Model:
    y(t) = x_true(t) + n_motion(t) + ε(t)

Peak Observation Model:
    t̂_i = t_true_i + ε_t + I_outlier * Δ_error

Error Propagation:
    E[error] = P_FP * E[large_error] + (1 - P_FP) * E[small_jitter]

Architecture: 4-Layer Pipeline
    Layer 1 → SQI (Window-Level Gatekeeper)
    Layer 2 → Preprocessing + Candidate Peak Detection
    Layer 3 → Score-Based Beat Validator (Core Engine)
    Layer 4 → ML Refinement (SUSPECT peaks only)

Changelog (v3) — all 12 loopholes from the architectural review addressed:
────────────────────────────────────────────────────────────────────────────
Fix #L1  (CRITICAL) BeatValidator: ghost data in IBI/amp/area deques on sensor
         disconnect. Added reset() method; PPGPeakDetectionSystem.on_sensor_reconnect()
         calls it and clears _last_accepted_ts.

Fix #L2  (HIGH)     BeatValidator._score_temporal: _last_accepted_ts now ages out
         after 5 × mu_IBI of silence, forcing a cold-start re-bootstrap instead of
         penalising every beat after a long SQI-reject run.

Fix #L3  (MEDIUM)   BeatValidator._score_morphology: replaced the monotone
         max(sharpness) with a leaky-max (decay_factor=0.9995 per beat ≈ 20-min
         half-life at 70 bpm). A single ADC glitch can no longer permanently
         depress morphology scores for the rest of a session.

Fix #L4  (CRITICAL) All timestamps now use a split-epoch representation
         (SplitTimestamp: epoch_sec uint32 + sub_samples uint16) so that
         delta-time arithmetic stays exact even after 48 h on float32 MCUs.
         PPGDetectionEngine.detect_candidates and PPGPeakDetectionSystem both
         accept/return SplitTimestamp; a float helper is provided for Python-side use.

Fix #L5  (HIGH)     PPGDetectionEngine._adaptive_threshold: _sig_lvl and
         _noise_lvl are now clamped to [0, MAX_LEVEL] after every EMA update and
         checked for NaN/Inf, preventing runaway accumulation under ADC saturation.

Fix #L6  (HIGH)     RobustPTTEstimator: update() now requires a wall-clock
         timestamp; estimate() and mad() return None if the most recent update
         is older than STALENESS_SEC (default 5 s), preventing stale PTT from
         leaking into BP estimates after an ECG lead-off event.

Fix #L7  (CRITICAL) MotionArtifactAnalyzer._spectral_entropy: scipy.signal.welch
         replaced with a self-contained O(N log N) Welch estimator built on
         numpy.fft.rfft with a pre-computed Hann window.  nperseg is validated to
         be a power-of-2 at construction time (not silently wrong at runtime).

Fix #L8  (CRITICAL) PPGDetectionEngine: replaced stateless filtfilt with a
         stateful sosfilt (second-order sections, lfilter-equivalent per section)
         that preserves IIR zi state across window boundaries.  The SOS
         coefficients are computed once at __init__ via butter(..., output='sos')
         and never recomputed.  This also eliminates the extra RAM required for
         filtfilt's backward pass and removes the window-edge artefacts.

Fix #L9  (CRITICAL) PPGDetectionEngine: added init_from_calibration() for the
         boot-time readiness gate.  The adaptive threshold is now seeded from
         measured calibration data instead of from the first (potentially
         transient) window.  PPGPeakDetectionSystem.boot_calibrate() orchestrates
         the flush + calibrate sequence.

Fix #L10 (HIGH)     BeatValidator._score_physio: added a clock-sync guard.
         If the difference between the PPG timestamp and the most recent ECG
         R-peak timestamp is larger than SYNC_FAULT_SEC (default 10 s) in either
         direction, PTT scoring returns neutral (0.5, None) and sets a
         sync_fault_detected flag instead of silently computing a wrong PTT.

Fix #L11 (CRITICAL) MotionArtifactAnalyzer._spectral_entropy: see Fix #L7.
         The hand-rolled Welch estimator uses only numpy; no scipy dependency in
         the hot path.  nperseg MUST be a power of 2 — validated at construction.

Fix #L12 (CRITICAL) PPGDetectionEngine: all filter coefficients are now stored
         in SOS form (butter output='sos') and applied via scipy.signal.sosfilt
         with persistent state (zi).  SOS form eliminates the float32 coefficient
         quantisation catastrophe that TF-form (b, a) exhibits for order ≥ 4.
         C++ ports should use arm_biquad_cascade_df1 with the sos coefficients
         hard-coded from the Python-side output (never recomputed on-device).

Dependencies: numpy, scipy (sosfilt + butter only), dataclasses, collections
=============================================================================
"""

from __future__ import annotations

import math
import struct
import warnings
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, List, Optional, Tuple

import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi, find_peaks

warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────────────────────
# FIX #L4 — SPLIT-EPOCH TIMESTAMP
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SplitTimestamp:
    """
    Exact timestamp for embedded systems.

    Stores time as (epoch_sec: int, sub_samples: int) so that
    delta-time arithmetic never loses sub-millisecond precision even
    after 48+ hours — a float32 at t=172 800 s has only ~20 ms resolution,
    which is larger than one sample period at 250 Hz (4 ms).

    On Python/PC, use SplitTimestamp.from_seconds(t) to construct and
    .to_seconds() to convert back.  In C++ firmware use uint32_t epoch_sec
    and uint16_t sub_samples with delta_t computed only on differences.
    """

    epoch_sec   : int    # whole seconds since session start (uint32 on MCU)
    sub_samples : int    # sample count within current second (0 … fs-1)

    # --- class-level fs: set once at system init --------------------------
    _fs: float = field(default=100.0, init=False, repr=False, compare=False)

    @classmethod
    def configure(cls, fs: float) -> None:
        """Call once at startup to set the sample rate used by all instances."""
        cls._fs = fs

    @classmethod
    def from_seconds(cls, t_sec: float, fs: float = None) -> "SplitTimestamp":
        """Convert an absolute float time (seconds) into a SplitTimestamp."""
        _fs = fs or cls._fs
        epoch   = int(t_sec)
        sub     = round((t_sec - epoch) * _fs)
        # Carry if rounding pushes sub past end of second
        if sub >= int(_fs):
            epoch += 1
            sub    = 0
        return cls(epoch_sec=epoch, sub_samples=sub)

    def to_seconds(self, fs: float = None) -> float:
        """Convert back to float seconds (fine for Python-side display)."""
        _fs = fs or self.__class__._fs
        return self.epoch_sec + self.sub_samples / _fs

    def delta_seconds(self, earlier: "SplitTimestamp", fs: float = None) -> float:
        """
        Compute self − earlier in seconds.

        Always computed as integer arithmetic on the split fields first,
        then a single floating-point division — no large-magnitude floats.
        """
        _fs = fs or self.__class__._fs
        ds  = int(self.epoch_sec)   - int(earlier.epoch_sec)
        dn  = int(self.sub_samples) - int(earlier.sub_samples)
        return ds + dn / _fs


def _split_ts(t_sec: float, fs: float) -> SplitTimestamp:
    """Convenience shorthand."""
    return SplitTimestamp.from_seconds(t_sec, fs=fs)


# ─────────────────────────────────────────────────────────────────────────────
# ENUMERATIONS & DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

class SQIDecision(Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class BeatDecision(Enum):
    ACCEPT  = "ACCEPT"
    REJECT  = "REJECT"
    SUSPECT = "SUSPECT"


@dataclass
class SQIResult:
    decision           : SQIDecision
    score              : float    # [0, 1]; higher = better quality
    perfusion_index    : float    # PI = (AC/DC)*100  [%]
    variance           : float
    signal_energy      : float
    zero_crossing_rate : float    # derivative instability proxy


@dataclass
class PeakCandidate:
    index           : int             # sample index in window
    timestamp       : SplitTimestamp  # Fix #L4: split-epoch, not raw float
    amplitude       : float
    rise_time       : float           # samples from trough→peak
    fall_time       : float           # samples from peak→next trough
    slope_asymmetry : float           # rise_slope / fall_slope
    peak_sharpness  : float           # 2nd derivative magnitude at peak
    pulse_area      : float           # trapezoidal integral under pulse [trough→trough]

    @property
    def timestamp_sec(self) -> float:
        """Float seconds — convenience for Python-side code."""
        return self.timestamp.to_seconds()


@dataclass
class ValidatedBeat:
    candidate      : PeakCandidate
    decision       : BeatDecision
    confidence     : float            # [0, 1]
    score_temporal : float
    score_morph    : float
    score_physio   : float
    score_amplitude: float            # amplitude consistency vs. running median
    score_area     : float            # pulse area consistency vs. running median
    ptt_ms         : Optional[float]  # Pulse Transit Time in ms (if ECG available)
    sync_fault     : bool = False     # Fix #L10: True if ECG/PPG clocks are desynced


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 1 — SIGNAL QUALITY INDEX (SQI)
# ─────────────────────────────────────────────────────────────────────────────

class SQILayer:
    """
    Window-level gatekeeper.  Operates on ~4-second sliding windows.

    Metrics
    -------
    Perfusion Index (PI):
        PI = (AC / DC) * 100
        AC = max(window) - min(window)   [pulsatile amplitude]
        DC = mean(window)                [baseline component]
        Threshold: PI >= 0.3 % (clinical lower bound for reliable sensing)

    Variance:
        sigma^2 = (1/N) sum (y_i - y_bar)^2
        Low sigma^2 → flat / noisy signal.
        Very high sigma^2 → motion burst.
        Accept band: [sigma^2_low, sigma^2_high]

    Signal Energy:
        E = (1/N) sum y_i^2

    Derivative Zero-Crossing Rate (ZCR):
        ZCR = (1/(N-1)) sum 1[dy_i * dy_{i-1} < 0]
        High ZCR → high-frequency motion contamination.
    """

    def __init__(
        self,
        fs            : float = 100.0,
        window_sec    : float = 4.0,
        pi_min        : float = 0.3,
        var_low       : float = 1e-6,
        var_high      : float = 1.0,
        zcr_max       : float = 0.35,
        sqi_threshold : float = 0.55,
        weights       : Tuple[float, float, float] = (0.4, 0.3, 0.3),
    ):
        self.fs            = fs
        self.window_n      = int(window_sec * fs)
        self.pi_min        = pi_min
        self.var_low       = var_low
        self.var_high      = var_high
        self.zcr_max       = zcr_max
        self.sqi_threshold = sqi_threshold
        self.w_pi, self.w_var, self.w_zcr = weights
        self._var_calibrated = False

    def calibrate_variance(self, clean_windows: list) -> None:
        """
        Set var_high from the 95th-percentile variance of clean baseline windows.
        Eliminates the sensor-gain dependency of var_high.
        """
        if not clean_windows:
            return
        variances = [float(np.var(w)) for w in clean_windows if len(w) > 0]
        if variances:
            self.var_high        = float(np.percentile(variances, 95)) * 3.0
            self.var_low         = float(np.percentile(variances,  5)) * 0.1
            self._var_calibrated = True

    def _score_perfusion(self, window: np.ndarray) -> Tuple[float, float]:
        dc    = np.mean(np.abs(window)) + 1e-9
        ac    = np.max(window) - np.min(window)
        pi    = (ac / dc) * 100.0
        score = 1.0 / (1.0 + math.exp(-3.0 * (pi - self.pi_min) / self.pi_min))
        return score, pi

    def _score_variance(self, window: np.ndarray) -> Tuple[float, float]:
        var = float(np.var(window))
        if var < self.var_low:
            score = 0.0
        elif var > self.var_high:
            score = max(0.0, 1.0 - ((var - self.var_high) / self.var_high) ** 0.5)
        else:
            log_range = math.log(self.var_high / self.var_low + 1e-12)
            score     = math.log(var / self.var_low + 1e-12) / log_range
            score     = max(0.0, min(1.0, score))
        return score, var

    def _score_zcr(self, window: np.ndarray) -> Tuple[float, float]:
        dy    = np.diff(window)
        signs = np.sign(dy)
        zc    = np.sum(signs[1:] * signs[:-1] < 0)
        zcr   = zc / max(len(dy) - 1, 1)
        score = max(0.0, 1.0 - zcr / self.zcr_max) if zcr < self.zcr_max else 0.0
        return score, zcr

    def evaluate(self, window: np.ndarray) -> SQIResult:
        if len(window) < self.window_n // 2:
            return SQIResult(SQIDecision.REJECT, 0.0, 0.0, 0.0, 0.0, 0.0)

        s_pi,  pi  = self._score_perfusion(window)
        s_var, var = self._score_variance(window)
        s_zcr, zcr = self._score_zcr(window)
        energy     = float(np.mean(window ** 2))

        sqi_score = self.w_pi * s_pi + self.w_var * s_var + self.w_zcr * s_zcr
        decision  = (SQIDecision.ACCEPT if sqi_score >= self.sqi_threshold
                     else SQIDecision.REJECT)

        return SQIResult(
            decision           = decision,
            score              = sqi_score,
            perfusion_index    = pi,
            variance           = var,
            signal_energy      = energy,
            zero_crossing_rate = zcr,
        )


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 2 — PRE-PROCESSING + CANDIDATE PEAK DETECTION
# ─────────────────────────────────────────────────────────────────────────────

class PPGDetectionEngine:
    """
    PPG equivalent of the Pan-Tompkins algorithm.

    v3 changes (Fixes #L4, #L5, #L8, #L9, #L12):

    Fix #L8 / #L12 — Stateful SOS bandpass filter
        butter(order, [low, high], output='sos') is called once at __init__.
        sosfilt is applied with a persistent zi state so that the IIR is
        continuous across window boundaries (no re-initialisation, no backward
        pass, no edge artefacts, no float32 quantisation instability).

        C++ porting note: export sos with
            from scipy.signal import butter
            sos = butter(4, [0.5, 8.0], btype='band', fs=250.0, output='sos')
            print(sos)   # copy into firmware as const float[][5]
        then use arm_biquad_cascade_df1_f32 with the same coefficients.

    Fix #L5 — Saturating EMA in adaptive threshold
        _sig_lvl and _noise_lvl are clamped to [0, _MAX_LEVEL] after every
        update and validated for NaN/Inf.

    Fix #L9 — boot calibration gate
        init_from_calibration(samples) seeds sig_lvl/noise_lvl from real
        clean data so _first_window is no longer silently wrong on boot.

    Fix #L4 — SplitTimestamp timestamps on all PeakCandidates.
    """

    # Fix #L5: clamp EMA levels to 2× a typical ADC full-scale in squared units.
    # Set to 2× (2^12)^2 = ~3.4e7 for a 12-bit ADC; scale for your hardware.
    _MAX_LEVEL: float = 3.4e7

    def __init__(
        self,
        fs                    : float = 100.0,
        bp_low                : float = 0.5,
        bp_high               : float = 8.0,
        bp_order              : int   = 4,
        ma_sec                : float = 0.200,
        threshold_alpha       : float = 0.125,
        min_peak_distance_sec : float = 0.33,
    ):
        self.fs            = fs
        self.bp_low        = bp_low
        self.bp_high       = bp_high
        self.bp_order      = bp_order
        self.ma_window     = max(1, round(ma_sec * fs))
        self.alpha         = threshold_alpha
        self.min_peak_dist = max(1, round(min_peak_distance_sec * fs))

        # Fix #L8 / #L12: SOS form — numerically stable at float32, order ≥ 4
        nyq       = fs / 2.0
        self._sos = butter(bp_order, [bp_low / nyq, bp_high / nyq],
                           btype="band", output="sos")
        # Fix #L8: persistent IIR state (zi) across window calls
        self._zi  = sosfilt_zi(self._sos) * 0.0   # zero-init, correct shape

        # Fix #L5 / #L9: threshold state
        self._sig_lvl  : float = 0.0
        self._noise_lvl: float = 0.0
        self._calibrated: bool = False  # Fix #L9: set True by init_from_calibration

        # Fix #L9: _first_window now only fires AFTER calibration or if no
        # calibration was done (graceful degradation)
        self._first_window: bool = True

        SplitTimestamp.configure(fs)  # Fix #L4: configure global FS

    # ── Fix #L9: boot-time calibration gate ────────────────────────────────

    def init_from_calibration(self, calib_samples: np.ndarray) -> None:
        """
        Seed the adaptive threshold from known-clean calibration data.
        Call this AFTER flushing the sensor power-on transient (≥ 0.5 s of
        samples) and BEFORE the first real process_window call.

        Parameters
        ----------
        calib_samples : 1-D array of raw PPG samples from the clean baseline
                        period (recommend ≥ 1 s = fs samples).
        """
        if len(calib_samples) < self.ma_window:
            return   # not enough data; fall back to first-window heuristic

        # Run through the signal chain to get a representative envelope
        filtered   = self._bandpass_init(calib_samples)
        deriv      = np.empty_like(filtered)
        deriv[0]   = 0.0
        deriv[1:]  = filtered[1:] - filtered[:-1]
        squared    = deriv ** 2
        kernel     = np.ones(self.ma_window) / self.ma_window
        envelope   = np.convolve(squared, kernel, mode="same")

        # Seed levels from 95th / 10th percentiles of the calibration envelope
        self._sig_lvl   = float(np.percentile(envelope, 95))
        self._noise_lvl = float(np.percentile(envelope, 10))
        self._sig_lvl   = min(self._sig_lvl,   self._MAX_LEVEL)
        self._noise_lvl = min(self._noise_lvl, self._MAX_LEVEL)
        self._calibrated   = True
        self._first_window = False

    def _bandpass_init(self, signal: np.ndarray) -> np.ndarray:
        """Bandpass filter without updating persistent zi — for calibration only."""
        out, _ = sosfilt(self._sos, signal.astype(np.float64),
                         zi=self._zi.copy())
        return out

    # ── Fix #L8: stateful sosfilt replaces filtfilt ─────────────────────────

    def _bandpass(self, signal: np.ndarray) -> np.ndarray:
        """
        Zero-initialised stateful IIR bandpass.

        Preserves filter state (zi) across window boundaries so the filter is
        continuous — no re-initialisation transient, no edge artefacts.
        Phase delay is ~20 ms at the lower band edge; compensate in peak
        timestamps if needed by subtracting group_delay / fs.
        """
        out, self._zi = sosfilt(self._sos, signal.astype(np.float64), zi=self._zi)
        return out

    @staticmethod
    def _derivative(signal: np.ndarray) -> np.ndarray:
        dy    = np.empty_like(signal)
        dy[0] = 0.0
        dy[1:] = signal[1:] - signal[:-1]
        return dy

    @staticmethod
    def _square(signal: np.ndarray) -> np.ndarray:
        return signal ** 2

    def _moving_average(self, signal: np.ndarray) -> np.ndarray:
        kernel = np.ones(self.ma_window) / self.ma_window
        return np.convolve(signal, kernel, mode="same")

    def _adaptive_threshold(self, envelope: np.ndarray) -> np.ndarray:
        """
        Pan-Tompkins dual-level adaptive threshold.

        Fix #L5: all EMA writes are clamped and NaN-guarded.
        Fix #L9: first-window bootstrap is skipped if init_from_calibration
                 already seeded the levels.
        """
        if self._first_window:
            # Fallback: seed from this window's envelope (boot without calibration)
            init_end = min(len(envelope), self.ma_window)
            self._sig_lvl   = float(np.mean(envelope[:init_end]))
            self._noise_lvl = self._sig_lvl * 0.5
            self._sig_lvl   = min(max(self._sig_lvl,   0.0), self._MAX_LEVEL)
            self._noise_lvl = min(max(self._noise_lvl, 0.0), self._MAX_LEVEL)
            self._first_window = False

        threshold = np.empty_like(envelope)
        th = self._noise_lvl + 0.25 * (self._sig_lvl - self._noise_lvl)

        for i, val in enumerate(envelope):
            # Fix #L5: clamp + NaN guard before and after each EMA update
            val = float(val)
            if not math.isfinite(val):
                val = 0.0
            if val > th:
                self._sig_lvl = self.alpha * val + (1.0 - self.alpha) * self._sig_lvl
            else:
                self._noise_lvl = self.alpha * val + (1.0 - self.alpha) * self._noise_lvl

            # Fix #L5: saturating clamp after update
            self._sig_lvl   = min(max(self._sig_lvl,   0.0), self._MAX_LEVEL)
            self._noise_lvl = min(max(self._noise_lvl, 0.0), self._MAX_LEVEL)
            if not math.isfinite(self._sig_lvl):
                self._sig_lvl = 0.0
            if not math.isfinite(self._noise_lvl):
                self._noise_lvl = 0.0

            th = self._noise_lvl + 0.25 * (self._sig_lvl - self._noise_lvl)
            threshold[i] = th

        return threshold

    # ── morphology extraction ──────────────────────────────────────────────

    def _extract_morphology(
        self,
        raw          : np.ndarray,
        peak_idx     : int,
        search_radius: int = 50,
    ) -> Tuple[float, float, float, float, float]:
        """
        Returns (rise_time, fall_time, slope_asymmetry, peak_sharpness, pulse_area).
        """
        n           = len(raw)
        left_start  = max(0, peak_idx - search_radius)
        right_end   = min(n - 1, peak_idx + search_radius)

        pre_segment  = raw[left_start : peak_idx + 1]
        post_segment = raw[peak_idx   : right_end  + 1]

        left_trough  = left_start + int(np.argmin(pre_segment))
        right_trough = peak_idx   + int(np.argmin(post_segment))

        rise_time = max(1, peak_idx - left_trough)
        fall_time = max(1, right_trough - peak_idx)

        peak_val        = raw[peak_idx]
        rise_amplitude  = peak_val - raw[left_trough]
        fall_amplitude  = peak_val - raw[right_trough]
        rise_slope      = rise_amplitude / rise_time
        fall_slope      = fall_amplitude / fall_time
        slope_asymmetry = rise_slope / (abs(fall_slope) + 1e-9)

        if 1 <= peak_idx < n - 1:
            sharpness = abs(raw[peak_idx + 1] - 2 * raw[peak_idx] + raw[peak_idx - 1])
        else:
            sharpness = 0.0

        _trapz    = (np.trapezoid if hasattr(np, "trapezoid") else np.trapz)
        pulse_area = float(_trapz(raw[left_trough : right_trough + 1]))

        return float(rise_time), float(fall_time), float(slope_asymmetry), float(sharpness), pulse_area

    # ── public API ─────────────────────────────────────────────────────────

    def detect_candidates(
        self,
        raw                : np.ndarray,
        window_offset_sec  : float = 0.0,
    ) -> List[PeakCandidate]:
        """
        Parameters
        ----------
        raw : np.ndarray
            Raw PPG window (should be SQI-accepted).
        window_offset_sec : float
            Absolute time of window start in seconds.
            Stored as SplitTimestamp for each candidate.  Fix #L4.

        Returns
        -------
        List[PeakCandidate]
        """
        filtered  = self._bandpass(raw)
        deriv     = self._derivative(filtered)
        squared   = self._square(deriv)
        envelope  = self._moving_average(squared)
        threshold = self._adaptive_threshold(envelope)

        peak_indices, _ = find_peaks(envelope, distance=self.min_peak_dist)

        candidates: List[PeakCandidate] = []
        for idx in peak_indices:
            if envelope[idx] <= threshold[idx]:
                continue

            search_l = max(0, idx - self.ma_window)
            search_r = min(len(filtered) - 1, idx + self.ma_window)
            local_peaks, _ = find_peaks(filtered[search_l : search_r + 1])

            if len(local_peaks) == 0:
                bp_peak = idx
            else:
                bp_peak = search_l + local_peaks[
                    np.argmax(filtered[search_l : search_r + 1][local_peaks])
                ]

            rise, fall, asym, sharp, area = self._extract_morphology(
                filtered, bp_peak)

            # Fix #L4: timestamp as SplitTimestamp
            peak_t_sec = window_offset_sec + bp_peak / self.fs
            ts = SplitTimestamp.from_seconds(peak_t_sec, fs=self.fs)

            candidates.append(PeakCandidate(
                index           = int(bp_peak),
                timestamp       = ts,
                amplitude       = float(filtered[bp_peak]),
                rise_time       = rise,
                fall_time       = fall,
                slope_asymmetry = asym,
                peak_sharpness  = sharp,
                pulse_area      = area,
            ))

        return candidates


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 3 — SCORE-BASED BEAT VALIDATOR
# ─────────────────────────────────────────────────────────────────────────────

class BeatValidator:
    """
    Core reliability engine.

    v3 changes (Fixes #L1, #L2, #L3, #L10):

    Fix #L1 — reset() method clears all deques and _last_accepted_ts.
        Call on_sensor_reconnect() after any I²C / sensor fault; the validator
        re-bootstraps cleanly from the first few beats after reconnection.

    Fix #L2 — Temporal staleness guard in _score_temporal.
        If delta_t > 5 × mu_IBI the timestamp is treated as stale and
        _last_accepted_ts is set to None (cold-start re-bootstrap). This
        prevents every post-reject beat from being penalised after a long
        SQI-reject run.

    Fix #L3 — Leaky-max for _max_sharpness.
        Instead of the monotone max(), each call applies a decay factor
        (default 0.9995 per beat ≈ 20-minute half-life at 70 bpm).
        A single ADC glitch cannot permanently depress morphology scores.

    Fix #L10 — ECG/PPG clock-sync guard in _score_physio.
        If |t_PPG - t_ECG_last| > SYNC_FAULT_SEC the method returns
        (0.5, None, sync_fault=True) rather than silently computing a
        wrong PTT from misaligned clocks.
    """

    # Fix #L2: treat _last_accepted_ts as stale if gap > this multiplier × mu_IBI
    _STALENESS_MU_MULT : float = 5.0

    # Fix #L10: maximum plausible absolute time offset between ECG and PPG clocks
    _SYNC_FAULT_SEC    : float = 10.0

    # Fix #L3: leaky-max decay per beat (half-life ≈ 1400 beats ≈ 20 min @ 70 bpm)
    _SHARPNESS_DECAY   : float = 0.9995

    def __init__(
        self,
        fs              : float = 100.0,
        ibi_buffer_size : int   = 20,
        k_mad           : float = 1.5,
        ptt_min_ms      : float = 100.0,
        ptt_max_ms      : float = 400.0,
        weights         : Tuple[float, float, float, float, float] = (0.25, 0.20, 0.25, 0.15, 0.15),
        accept_threshold: float = 0.65,
        reject_threshold: float = 0.35,
    ):
        self.fs         = fs
        self.k_mad      = k_mad
        self.ptt_min    = ptt_min_ms
        self.ptt_max    = ptt_max_ms
        self.w_temp, self.w_morph, self.w_physio, self.w_amp, self.w_area = weights
        self.accept_th  = accept_threshold
        self.reject_th  = reject_threshold

        self._ibi_buffer_size = ibi_buffer_size
        self._reset_state()

    # ── Fix #L1: state reset API ────────────────────────────────────────────

    def _reset_state(self) -> None:
        """Zero all rolling buffers and invalidate the last accepted timestamp."""
        self._ibi_buffer  : Deque[float]    = deque(maxlen=self._ibi_buffer_size)
        self._amp_buffer  : Deque[float]    = deque(maxlen=self._ibi_buffer_size)
        self._area_buffer : Deque[float]    = deque(maxlen=self._ibi_buffer_size)
        self._last_accepted_ts : Optional[SplitTimestamp] = None
        self._max_sharpness    : float = 1e-9

    def reset(self) -> None:
        """
        Fix #L1: call this after a sensor disconnect/reconnect.
        Clears all buffers so stale pre-disconnect data cannot corrupt
        the first-beat validations after reconnection.
        """
        self._reset_state()

    # ── robust IBI statistics ──────────────────────────────────────────────

    def _robust_ibi_stats(self) -> Tuple[float, float]:
        """Returns (median_IBI, sigma_IBI) in seconds. sigma = 1.4826 * MAD."""
        if len(self._ibi_buffer) < 3:
            return 0.85, 0.15   # physiological prior
        ibis  = np.array(self._ibi_buffer)
        mu    = float(np.median(ibis))
        mad   = float(np.median(np.abs(ibis - mu)))
        sigma = max(mad * 1.4826, 0.02)   # floor at 20 ms
        return mu, sigma

    @staticmethod
    def _sigmoid(x: float, gain: float = 5.0) -> float:
        return 1.0 / (1.0 + math.exp(-gain * x))

    def _score_temporal(self, candidate: PeakCandidate) -> float:
        """
        Fix #L2: temporal staleness guard.
        If _last_accepted_ts is None or the gap is > 5 × mu_IBI, treat as
        cold-start (return neutral 0.70 and invalidate the stale timestamp).
        """
        if self._last_accepted_ts is None:
            return 0.70

        delta_t = candidate.timestamp.delta_seconds(self._last_accepted_ts)
        if delta_t <= 0:
            return 0.0

        mu_ibi, sigma_ibi = self._robust_ibi_stats()

        # Fix #L2: age-out stale timestamp instead of penalising every beat
        if delta_t > self._STALENESS_MU_MULT * mu_ibi:
            self._last_accepted_ts = None   # force re-bootstrap
            return 0.70

        # Hard missed-beat guard — only once buffer is populated (Fix #23 retained)
        if len(self._ibi_buffer) >= 3 and delta_t > 2.0 * mu_ibi:
            return 0.10

        score = math.exp(-abs(delta_t - mu_ibi) / (self.k_mad * sigma_ibi + 1e-9))
        return float(np.clip(score, 0.0, 1.0))

    def _score_morphology(self, candidate: PeakCandidate) -> float:
        """
        Fix #L3: leaky-max for peak sharpness so a single ADC glitch cannot
        permanently suppress the sharpness sub-score for an entire session.
        """
        s_rf = self._sigmoid(candidate.fall_time - candidate.rise_time, gain=0.1)
        s_sa = self._sigmoid(candidate.slope_asymmetry - 1.0, gain=2.0)

        # Fix #L3: leaky-max decay (half-life ≈ 20 min at 70 bpm)
        self._max_sharpness = max(
            candidate.peak_sharpness,
            self._SHARPNESS_DECAY * self._max_sharpness,
        )
        s_sh = candidate.peak_sharpness / (self._max_sharpness + 1e-9)
        return float(np.clip((s_rf + s_sa + s_sh) / 3.0, 0.0, 1.0))

    def _score_amplitude(self, candidate: PeakCandidate) -> float:
        if len(self._amp_buffer) < 3:
            return 0.5
        med_amp = float(np.median(self._amp_buffer)) + 1e-9
        dev     = abs(candidate.amplitude - med_amp) / med_amp
        return float(np.clip(1.0 - dev, 0.0, 1.0))

    def _score_area(self, candidate: PeakCandidate) -> float:
        if len(self._area_buffer) < 3:
            return 0.5
        med_area = float(np.median(self._area_buffer)) + 1e-9
        dev      = abs(candidate.pulse_area - med_area) / med_area
        return float(np.clip(1.0 - dev, 0.0, 1.0))

    def _score_physio(
        self,
        candidate      : PeakCandidate,
        ecg_r_peaks_ts : Optional[List[float]],
    ) -> Tuple[float, Optional[float], bool]:
        """
        PTT = t_PPG_peak − t_ECG_R_peak_prev  (ms)

        Fix #L10: clock-sync guard.
        If the nearest ECG timestamp differs from the PPG timestamp by more than
        SYNC_FAULT_SEC, the clocks are not aligned — return neutral score and
        signal the fault to the caller.

        Returns (score, ptt_ms, sync_fault_flag).
        """
        if not ecg_r_peaks_ts:
            return 0.50, None, False

        ppg_t = candidate.timestamp_sec

        # Fix #L10: check for clock desynchronisation before any PTT computation
        nearest_ecg_t = min(ecg_r_peaks_ts, key=lambda t: abs(t - ppg_t))
        if abs(ppg_t - nearest_ecg_t) > self._SYNC_FAULT_SEC:
            return 0.50, None, True   # sync_fault = True

        valid_ecg = [t for t in ecg_r_peaks_ts if t < ppg_t]
        if not valid_ecg:
            return 0.50, None, False

        ptt_s = (ppg_t - valid_ecg[-1]) * 1000.0   # ms
        if ptt_s <= 0:
            return 0.0, None, False

        if self.ptt_min <= ptt_s <= self.ptt_max:
            centre = (self.ptt_min + self.ptt_max) / 2.0
            half_w = (self.ptt_max - self.ptt_min) / 2.0
            score  = 1.0 - abs(ptt_s - centre) / half_w
            score  = float(np.clip(score, 0.5, 1.0))
        else:
            overshoot  = max(0.0, ptt_s - self.ptt_max)
            undershoot = max(0.0, self.ptt_min - ptt_s)
            penalty    = (overshoot + undershoot) / self.ptt_max
            score      = max(0.0, 0.5 - penalty)

        return score, ptt_s, False

    def validate(
        self,
        candidate      : PeakCandidate,
        sqi_score      : float = 1.0,
        ecg_r_peaks_ts : Optional[List[float]] = None,
    ) -> ValidatedBeat:
        """
        Classify one beat.

        Parameters
        ----------
        candidate       : PeakCandidate
        sqi_score       : [0,1] from Layer 1; modulates confidence only.
        ecg_r_peaks_ts  : all ECG R-peak timestamps (float seconds) in window.

        Returns
        -------
        ValidatedBeat
        """
        s_t              = self._score_temporal(candidate)
        s_m              = self._score_morphology(candidate)
        s_p, ptt_ms, sf  = self._score_physio(candidate, ecg_r_peaks_ts)
        s_a              = self._score_amplitude(candidate)
        s_ar             = self._score_area(candidate)

        total = (self.w_temp   * s_t  +
                 self.w_morph  * s_m  +
                 self.w_physio * s_p  +
                 self.w_amp    * s_a  +
                 self.w_area   * s_ar)

        confidence = float(np.clip(total * sqi_score, 0.0, 1.0))

        if total >= self.accept_th:
            decision = BeatDecision.ACCEPT
        elif total < self.reject_th:
            decision = BeatDecision.REJECT
        else:
            decision = BeatDecision.SUSPECT

        # Update buffers ONLY on accepted beats to prevent buffer poisoning
        if decision == BeatDecision.ACCEPT and self._last_accepted_ts is not None:
            ibi = candidate.timestamp.delta_seconds(self._last_accepted_ts)
            if 0.3 <= ibi <= 2.0:
                self._ibi_buffer.append(ibi)

        if decision == BeatDecision.ACCEPT:
            self._last_accepted_ts = candidate.timestamp
            self._amp_buffer.append(candidate.amplitude)
            self._area_buffer.append(candidate.pulse_area)

        return ValidatedBeat(
            candidate      = candidate,
            decision       = decision,
            confidence     = confidence,
            score_temporal = s_t,
            score_morph    = s_m,
            score_physio   = s_p,
            score_amplitude= s_a,
            score_area     = s_ar,
            ptt_ms         = ptt_ms,
            sync_fault     = sf,
        )


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 4 — ML REFINEMENT (SUSPECT PEAKS ONLY)
# ─────────────────────────────────────────────────────────────────────────────

class MLRefinementLayer:
    """
    Processes ONLY SUSPECT beats from Layer 3.

    Feature vector x (8-dimensional):
        [amplitude, rise_time, fall_time, slope_asymmetry,
         peak_sharpness, ibi_deviation, sqi_score, ptt_ms]

    v3: heuristic fallback weights ibi_score + sqi only (Fix #22 retained).
    """

    def __init__(self, model=None, decision_threshold: float = 0.60):
        self.model     = model
        self.threshold = decision_threshold

    def _heuristic_fallback(self, x: np.ndarray) -> float:
        ibi_deviation = x[5]
        sqi           = x[6]
        ibi_score     = max(0.0, 1.0 - ibi_deviation / 3.0)
        return float(np.clip((ibi_score + sqi) / 2.0, 0.0, 1.0))

    def refine(
        self,
        beat         : ValidatedBeat,
        sqi_score    : float,
        ibi_deviation: float,
    ) -> ValidatedBeat:
        if beat.decision != BeatDecision.SUSPECT:
            return beat

        x = np.array([
            beat.candidate.amplitude,
            beat.candidate.rise_time,
            beat.candidate.fall_time,
            beat.candidate.slope_asymmetry,
            beat.candidate.peak_sharpness,
            ibi_deviation,
            sqi_score,
            beat.ptt_ms if beat.ptt_ms is not None else -1.0,
        ], dtype=np.float32)

        if self.model is not None:
            try:
                prob = float(self.model.predict_proba(x.reshape(1, -1))[0, 1])
            except Exception:
                prob = self._heuristic_fallback(x)
        else:
            prob = self._heuristic_fallback(x)

        new_decision = (BeatDecision.ACCEPT if prob >= self.threshold
                        else BeatDecision.REJECT)

        return ValidatedBeat(
            candidate      = beat.candidate,
            decision       = new_decision,
            confidence     = float(np.clip(prob, 0.0, 1.0)),
            score_temporal = beat.score_temporal,
            score_morph    = beat.score_morph,
            score_physio   = beat.score_physio,
            score_amplitude= beat.score_amplitude,
            score_area     = beat.score_area,
            ptt_ms         = beat.ptt_ms,
            sync_fault     = beat.sync_fault,
        )


# ─────────────────────────────────────────────────────────────────────────────
# ROBUST PTT ESTIMATOR  (Fix #L6)
# ─────────────────────────────────────────────────────────────────────────────

class RobustPTTEstimator:
    """
    Median-based PTT estimator with staleness guard.

    Fix #L6: update() now stores the wall-clock time of each sample.
    estimate() and mad() return None if the most recent update is older
    than STALENESS_SEC, preventing stale PTT values from persisting after
    an ECG lead-off event.
    """

    STALENESS_SEC: float = 5.0   # Fix #L6: invalidate if no update within 5 s

    def __init__(self, buffer_size: int = 30):
        self._buffer     : Deque[float]          = deque(maxlen=buffer_size)
        self._update_ts  : Deque[float]          = deque(maxlen=buffer_size)
        self._last_update: Optional[float]       = None   # wall-clock seconds

    def update(self, ptt_ms: float, wall_sec: float) -> None:
        """
        Parameters
        ----------
        ptt_ms   : measured PTT in milliseconds
        wall_sec : wall-clock time of measurement (seconds); use a monotonic
                   clock (e.g., time.monotonic() or FreeRTOS xTaskGetTickCount()
                   converted to seconds).
        """
        if 0 < ptt_ms < 2000:
            self._buffer.append(ptt_ms)
            self._update_ts.append(wall_sec)
            self._last_update = wall_sec

    def estimate(self, now_sec: Optional[float] = None) -> Optional[float]:
        """
        Fix #L6: returns None if the buffer has not been updated within
        STALENESS_SEC, signalling that ECG is disconnected or unavailable.
        """
        if len(self._buffer) < 3:
            return None
        if now_sec is not None and self._last_update is not None:
            if (now_sec - self._last_update) > self.STALENESS_SEC:
                return None   # ECG lead-off — do not report stale PTT
        return float(np.median(self._buffer))

    def mad(self, now_sec: Optional[float] = None) -> Optional[float]:
        if len(self._buffer) < 3:
            return None
        if now_sec is not None and self._last_update is not None:
            if (now_sec - self._last_update) > self.STALENESS_SEC:
                return None
        arr = np.array(self._buffer)
        return float(np.median(np.abs(arr - np.median(arr))))


# ─────────────────────────────────────────────────────────────────────────────
# MOTION ARTIFACT ANALYSIS  (Fixes #L7 / #L11)
# ─────────────────────────────────────────────────────────────────────────────

class MotionArtifactAnalyzer:
    """
    Fix #L7 / #L11: scipy.signal.welch removed from the hot path.

    _spectral_entropy now uses a self-contained Welch estimator built on
    numpy.fft.rfft with a pre-computed Hann window.  This is O(N log N),
    has no runtime scipy dependency, and can be ported directly to
    CMSIS-DSP arm_rfft_fast_f32 on Cortex-M4.

    nperseg MUST be a power of 2.  This is validated at construction time
    so MCU ports fail loudly during init rather than silently at runtime.

    Fix #L26 (retained): temporal lockout hysteresis.
    """

    def __init__(
        self,
        fs               : float = 100.0,
        baseline_var     : float = 1.0,
        var_ratio_thresh : float = 5.0,
        entropy_thresh   : float = 3.5,
        corr_thresh      : float = 0.70,
        lockout_windows  : int   = 2,
        nperseg          : int   = 64,    # Fix #L7/L11: MUST be power of 2
    ):
        self.fs               = fs
        self.baseline_var     = baseline_var
        self.var_ratio_thresh = var_ratio_thresh
        self.entropy_thresh   = entropy_thresh
        self.corr_thresh      = corr_thresh
        self.lockout_windows  = lockout_windows
        self._template        : Optional[np.ndarray] = None
        self._lockout_remaining: int = 0

        # Fix #L7/L11: validate nperseg is power of 2 at construction time
        if nperseg <= 0 or (nperseg & (nperseg - 1)) != 0:
            raise ValueError(
                f"nperseg={nperseg} must be a positive power of 2 "
                f"(required for CMSIS-DSP RFFT portability)."
            )
        self._nperseg = nperseg

        # Pre-compute Hann window — done once, reused every call
        # (C++ equivalent: static const float HANN[N] in firmware header)
        self._hann = np.hanning(nperseg).astype(np.float64)

    def set_template(self, clean_beat: np.ndarray) -> None:
        norm = clean_beat - np.mean(clean_beat)
        denom = np.std(norm)
        self._template = norm / (denom + 1e-9)

    def _spectral_entropy(self, window: np.ndarray) -> float:
        """
        Fix #L7 / #L11: hand-rolled Welch estimator using numpy.fft.rfft.
        No scipy in this path — directly portable to CMSIS-DSP.

        Steps identical to scipy.signal.welch with default parameters:
          - 50% overlap
          - Hann window
          - |RFFT|^2 periodogram averaged over segments
          - Entropy computed on normalised PSD
        """
        n       = len(window)
        nperseg = self._nperseg
        hop     = nperseg // 2   # 50% overlap

        psd     = np.zeros(nperseg // 2 + 1, dtype=np.float64)
        n_segs  = 0

        for start in range(0, n - nperseg + 1, hop):
            seg = window[start : start + nperseg].astype(np.float64)
            seg = seg * self._hann
            X   = np.fft.rfft(seg, n=nperseg)
            psd += (X.real ** 2 + X.imag ** 2)
            n_segs += 1

        if n_segs == 0:
            return 0.0

        psd  /= n_segs
        total = psd.sum() + 1e-12
        pn    = psd / total
        pn    = pn[pn > 0]
        return float(-np.sum(pn * np.log2(pn)))

    def _waveform_correlation(self, window: np.ndarray) -> float:
        if self._template is None or len(window) < len(self._template):
            return 1.0
        seg     = window[:len(self._template)]
        seg_n   = (seg - np.mean(seg)) / (np.std(seg) + 1e-9)
        return float(np.corrcoef(seg_n, self._template)[0, 1])

    def analyze(self, window: np.ndarray) -> dict:
        var_ratio  = float(np.var(window)) / (self.baseline_var + 1e-9)
        entropy    = self._spectral_entropy(window)
        corr       = self._waveform_correlation(window)

        raw_motion = (
            var_ratio > self.var_ratio_thresh
            or entropy > self.entropy_thresh
            or corr    < self.corr_thresh
        )

        # Fix #L26 (retained): hysteresis lockout
        in_lockout = (not raw_motion) and (self._lockout_remaining > 0)
        if raw_motion:
            self._lockout_remaining = self.lockout_windows
        elif self._lockout_remaining > 0:
            self._lockout_remaining -= 1

        motion_detected = raw_motion or in_lockout

        return {
            "motion_detected" : motion_detected,
            "variance_ratio"  : var_ratio,
            "spectral_entropy": entropy,
            "waveform_corr"   : corr,
        }


# ─────────────────────────────────────────────────────────────────────────────
# ERROR SENSITIVITY ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

class ErrorSensitivityAnalyzer:
    """
    Quantifies the effect of false positive peaks on PTT and BP estimation.

    E[PTT_error] = P_FP * E[|ε_large|] + (1 - P_FP) * E[|ε_jitter|]

    Stability region:
        P_FP_critical ~ E[|ε_jitter|] / (E[|ε_large|] - E[|ε_jitter|]) ~ 5%
    """

    @staticmethod
    def expected_ptt_error(
        p_fp       : float,
        e_large_ms : float = 200.0,
        e_jitter_ms: float = 10.0,
    ) -> float:
        return p_fp * e_large_ms + (1.0 - p_fp) * e_jitter_ms

    @staticmethod
    def bp_error_mmhg(ptt_error_ms: float, k: float = 0.75) -> float:
        return k * ptt_error_ms

    @staticmethod
    def stability_analysis(
        p_fp_range  : Optional[np.ndarray] = None,
        e_large_ms  : float = 200.0,
        e_jitter_ms : float = 10.0,
        k_bp        : float = 0.75,
    ) -> dict:
        if p_fp_range is None:
            p_fp_range = np.linspace(0.0, 0.20, 200)
        ptt_errors = ErrorSensitivityAnalyzer.expected_ptt_error(
            p_fp_range, e_large_ms, e_jitter_ms)
        bp_errors  = ErrorSensitivityAnalyzer.bp_error_mmhg(ptt_errors, k_bp)
        critical   = e_jitter_ms / max(e_large_ms - e_jitter_ms, 1e-9)
        return {
            "p_fp"         : p_fp_range,
            "ptt_error_ms" : ptt_errors,
            "bp_error_mmhg": bp_errors,
            "p_fp_critical": critical,
        }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SYSTEM ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

class PPGPeakDetectionSystem:
    """
    Top-level orchestrator of the 4-layer pipeline.

    v3 additions (Fixes #L1, #L4, #L6, #L9):

    Fix #L1 — on_sensor_reconnect():
        Calls validator.reset() and clears the PTT estimator.
        Must be invoked from the I²C/ISR error handler on any sensor fault.

    Fix #L9 — boot_calibrate():
        Flushes sensor power-on transient (flush_sec), collects clean samples,
        passes them to PPGDetectionEngine.init_from_calibration() and
        SQILayer.calibrate_variance().  Must be called before the first
        process_window() call in production firmware.

    Fix #L4 — process_window() now propagates wall_sec to RobustPTTEstimator
        so the staleness guard (Fix #L6) works correctly.

    Usage
    -----
    fs     = 250.0
    system = PPGPeakDetectionSystem(fs=fs, ecg_available=True)
    system.boot_calibrate(collect_fn=lambda n: sensor.read(n))   # Fix #L9
    for window, ts, ecg_peaks, wall_sec in stream:
        results = system.process_window(window, ts, ecg_peaks, wall_sec=wall_sec)
    """

    def __init__(
        self,
        fs           : float = 100.0,
        ml_model              = None,
        ecg_available: bool  = False,
    ):
        self.fs            = fs
        self.ecg_available = ecg_available

        SplitTimestamp.configure(fs)   # Fix #L4

        self.sqi_layer       = SQILayer(fs=fs)
        self.detector        = PPGDetectionEngine(fs=fs)
        self.validator       = BeatValidator(fs=fs)
        self.ml_refiner      = MLRefinementLayer(model=ml_model)
        self.ptt_estimator   = RobustPTTEstimator()
        self.motion_analyzer = MotionArtifactAnalyzer(fs=fs)

        self._wall_sec       : float = 0.0   # running wall clock if not provided

    # ── Fix #L9: boot calibration gate ─────────────────────────────────────

    def boot_calibrate(
        self,
        calib_samples: np.ndarray,
        flush_samples: Optional[int] = None,
    ) -> None:
        """
        Fix #L9: seed adaptive threshold and SQI variance bounds from known-clean
        data collected AFTER the sensor power-on transient has been discarded.

        Parameters
        ----------
        calib_samples : 1-D array of raw PPG from the resting calibration period
                        (recommend ≥ 1 s; must come AFTER flush_samples are
                        discarded by the caller).
        flush_samples : if provided, the first flush_samples of calib_samples are
                        discarded here (convenience wrapper for Python testing).
        """
        if flush_samples and flush_samples < len(calib_samples):
            calib_samples = calib_samples[flush_samples:]

        self.detector.init_from_calibration(calib_samples)

        # Split calib into windows for SQI variance calibration
        win_n    = self.sqi_layer.window_n
        windows  = [calib_samples[i : i + win_n]
                    for i in range(0, len(calib_samples) - win_n, win_n // 2)
                    if i + win_n <= len(calib_samples)]
        if windows:
            self.sqi_layer.calibrate_variance(windows)

    # ── Fix #L1: sensor reconnect handler ──────────────────────────────────

    def on_sensor_reconnect(self) -> None:
        """
        Fix #L1: call this from the I²C error handler whenever a sensor
        disconnect/reconnect event is detected.

        Clears all validator buffers and the PTT estimator so that stale
        pre-disconnect data cannot corrupt validations after reconnection.
        """
        self.validator.reset()
        # Clear PTT buffer — old PTT values from before disconnect are invalid
        self.ptt_estimator = RobustPTTEstimator()

    # ── IBI deviation helper ────────────────────────────────────────────────

    def _compute_ibi_deviation_for(self, candidate: PeakCandidate) -> float:
        """
        Compute IBI deviation BEFORE validate() updates _last_accepted_ts.
        Fix #25 (retained from v2).
        """
        if self.validator._last_accepted_ts is None:
            return 0.0
        delta   = candidate.timestamp.delta_seconds(self.validator._last_accepted_ts)
        mu, sigma = self.validator._robust_ibi_stats()
        return abs(delta - mu) / (sigma + 1e-9)

    # ── main processing entry point ─────────────────────────────────────────

    def process_window(
        self,
        raw_window        : np.ndarray,
        window_start_sec  : float = 0.0,
        ecg_r_peaks_ts    : Optional[List[float]] = None,
        wall_sec          : Optional[float] = None,
    ) -> dict:
        """
        Parameters
        ----------
        raw_window       : raw PPG samples for the current window.
        window_start_sec : absolute time of window start in seconds.
        ecg_r_peaks_ts   : all ECG R-peak timestamps (float seconds) in window.
        wall_sec         : current wall-clock time in seconds (monotonic).
                           Used by RobustPTTEstimator staleness guard (Fix #L6).
                           If None, estimated from window_start_sec.

        Returns
        -------
        dict with keys:
            sqi_result       : SQIResult
            motion_analysis  : dict
            accepted_beats   : List[ValidatedBeat]
            rejected_beats   : List[ValidatedBeat]
            ptt_estimate_ms  : Optional[float]
            ptt_mad_ms       : Optional[float]
            sync_fault       : bool  — True if any beat had an ECG/PPG sync fault
        """
        # Infer wall clock if not provided
        if wall_sec is None:
            wall_sec = window_start_sec + len(raw_window) / self.fs

        # Layer 1: SQI gate
        sqi_result  = self.sqi_layer.evaluate(raw_window)
        motion_info = self.motion_analyzer.analyze(raw_window)

        if sqi_result.decision == SQIDecision.REJECT:
            return {
                "sqi_result"     : sqi_result,
                "motion_analysis": motion_info,
                "accepted_beats" : [],
                "rejected_beats" : [],
                "ptt_estimate_ms": self.ptt_estimator.estimate(now_sec=wall_sec),
                "ptt_mad_ms"     : self.ptt_estimator.mad(now_sec=wall_sec),
                "sync_fault"     : False,
            }

        # Layer 2: Candidate detection
        candidates = self.detector.detect_candidates(raw_window, window_start_sec)

        # Layers 3 & 4: Validation and optional ML refinement
        accepted : List[ValidatedBeat] = []
        rejected : List[ValidatedBeat] = []
        any_sync_fault = False

        for cand in candidates:
            ecg_ts      = ecg_r_peaks_ts if self.ecg_available else None
            ibi_dev_pre = self._compute_ibi_deviation_for(cand)

            beat = self.validator.validate(cand, sqi_result.score, ecg_ts)

            if beat.sync_fault:
                any_sync_fault = True

            if beat.decision == BeatDecision.SUSPECT:
                beat = self.ml_refiner.refine(beat, sqi_result.score, ibi_dev_pre)

            if beat.decision == BeatDecision.ACCEPT:
                accepted.append(beat)
                if beat.ptt_ms is not None and not beat.sync_fault:
                    # Fix #L6: pass wall_sec so staleness guard is accurate
                    self.ptt_estimator.update(beat.ptt_ms, wall_sec=wall_sec)
            else:
                rejected.append(beat)

        return {
            "sqi_result"     : sqi_result,
            "motion_analysis": motion_info,
            "accepted_beats" : accepted,
            "rejected_beats" : rejected,
            "ptt_estimate_ms": self.ptt_estimator.estimate(now_sec=wall_sec),
            "ptt_mad_ms"     : self.ptt_estimator.mad(now_sec=wall_sec),
            "sync_fault"     : any_sync_fault,
        }


# ─────────────────────────────────────────────────────────────────────────────
# DEMONSTRATION & UNIT-LEVEL TESTS
# ─────────────────────────────────────────────────────────────────────────────

def _generate_synthetic_ppg(
    fs             : float = 100.0,
    duration_sec   : float = 10.0,
    hr_bpm         : float = 70.0,
    snr_db         : float = 20.0,
    add_motion     : bool  = False,
    motion_freq_hz : float = 2.0,
    motion_amplitude: float = 0.3,
) -> np.ndarray:
    t    = np.arange(int(duration_sec * fs)) / fs
    f_hr = hr_bpm / 60.0
    ppg  = (np.sin(2 * np.pi * f_hr * t)
            + 0.3 * np.sin(4 * np.pi * f_hr * t)
            + 0.1 * np.sin(6 * np.pi * f_hr * t))

    sig_power   = np.mean(ppg ** 2)
    noise_power = sig_power / (10 ** (snr_db / 10.0))
    epsilon     = np.random.randn(len(t)) * math.sqrt(noise_power)

    motion = 0.0
    if add_motion:
        motion = motion_amplitude * np.sin(2 * np.pi * motion_freq_hz * t)
        burst  = np.ones_like(t)
        burst[int(3 * fs) : int(5 * fs)] = 2.5
        motion *= burst

    return ppg + motion + epsilon


def run_demo():
    import time as _time

    print("=" * 70)
    print("PPG Peak Detection & Validation System — Demo  (v3)")
    print("=" * 70)

    fs = 100.0
    np.random.seed(42)
    SplitTimestamp.configure(fs)

    window_n = int(4.0 * fs)
    step_n   = int(1.0 * fs)

    # ── Test 1: Clean signal ───────────────────────────────────────────────
    print("\n[Test 1] Clean PPG signal (SNR = 25 dB)")
    ppg_clean = _generate_synthetic_ppg(fs=fs, duration_sec=10.0, snr_db=25.0)
    system    = PPGPeakDetectionSystem(fs=fs)

    # Fix #L9: boot calibration from first 2s (discard first 0.5s as flush)
    system.boot_calibrate(ppg_clean[:int(2*fs)], flush_samples=int(0.5*fs))

    n_windows = total_accepted = total_rejected = 0
    for start in range(0, len(ppg_clean) - window_n, step_n):
        win     = ppg_clean[start : start + window_n]
        t_start = start / fs
        t_wall  = t_start + window_n / fs
        result  = system.process_window(win,
                                         window_start_sec=t_start,
                                         wall_sec=t_wall)
        n_windows      += 1
        total_accepted += len(result["accepted_beats"])
        total_rejected += len(result["rejected_beats"])

    print(f"  Windows processed : {n_windows}")
    print(f"  Accepted beats    : {total_accepted}")
    print(f"  Rejected beats    : {total_rejected}")
    print(f"  PTT estimate      : {system.ptt_estimator.estimate()}")

    # ── Test 2: Signal with motion artifact ───────────────────────────────
    print("\n[Test 2] PPG with motion artifact (2 Hz burst, sec 3-5)")
    ppg_motion = _generate_synthetic_ppg(
        fs=fs, duration_sec=10.0, snr_db=20.0,
        add_motion=True, motion_freq_hz=2.0, motion_amplitude=0.4,
    )
    system2 = PPGPeakDetectionSystem(fs=fs)
    system2.boot_calibrate(ppg_motion[:int(2*fs)], flush_samples=int(0.5*fs))

    sqi_accept = sqi_reject = 0
    for start in range(0, len(ppg_motion) - window_n, step_n):
        win    = ppg_motion[start : start + window_n]
        result = system2.process_window(win, window_start_sec=start/fs,
                                         wall_sec=(start + window_n)/fs)
        if result["sqi_result"].decision == SQIDecision.ACCEPT:
            sqi_accept += 1
        else:
            sqi_reject += 1

    total_win = sqi_accept + sqi_reject
    print(f"  SQI ACCEPT windows: {sqi_accept}")
    print(f"  SQI REJECT windows: {sqi_reject}")
    print(f"  Reject rate       : {sqi_reject / max(total_win, 1):.1%}")

    # ── Test 3: Error sensitivity analysis ────────────────────────────────
    print("\n[Test 3] Error Sensitivity Analysis")
    analysis = ErrorSensitivityAnalyzer.stability_analysis(
        p_fp_range  = np.array([0.01, 0.05, 0.10, 0.20]),
        e_large_ms  = 200.0,
        e_jitter_ms = 10.0,
        k_bp        = 0.75,
    )
    print(f"  Critical P_FP: {analysis['p_fp_critical']:.3f}")
    for pfp, ptt_err, bp_err in zip(
        analysis["p_fp"], analysis["ptt_error_ms"], analysis["bp_error_mmhg"]
    ):
        print(f"  P_FP={pfp:.2f} -> E[PTT_err]={ptt_err:.1f} ms, "
              f"E[BP_err]={bp_err:.2f} mmHg")

    # ── Test 4: SQI layer unit tests ───────────────────────────────────────
    print("\n[Test 4] SQI Layer Unit Tests")
    sqi_layer = SQILayer(fs=100.0)

    t_good = np.linspace(0, 4, 400)
    good   = np.sin(2 * np.pi * 1.2 * t_good) + 0.05 * np.random.randn(400)
    res    = sqi_layer.evaluate(good)
    print(f"  Good signal  -> {res.decision.value}, SQI={res.score:.3f}, "
          f"PI={res.perfusion_index:.2f}%")

    flat = np.ones(400) * 0.001 + 0.0001 * np.random.randn(400)
    res2 = sqi_layer.evaluate(flat)
    print(f"  Flat signal  -> {res2.decision.value}, SQI={res2.score:.3f}")

    noisy = np.sin(2 * np.pi * 1.2 * t_good) + 2.0 * np.random.randn(400)
    res3  = sqi_layer.evaluate(noisy)
    print(f"  Noisy signal -> {res3.decision.value}, SQI={res3.score:.3f}")

    # ── Test 5: Amplitude & area scoring ──────────────────────────────────
    print("\n[Test 5] Amplitude & Area Score Consistency Check")
    validator = BeatValidator(fs=fs)

    def _make_candidate(ts_sec, amp, rise=10.0, fall=15.0, area=50.0):
        return PeakCandidate(
            index          = int(ts_sec * fs),
            timestamp      = SplitTimestamp.from_seconds(ts_sec, fs=fs),
            amplitude      = amp,
            rise_time      = rise,
            fall_time      = fall,
            slope_asymmetry= 1.5,
            peak_sharpness = 0.05,
            pulse_area     = area,
        )

    for i in range(5):
        validator.validate(_make_candidate(ts_sec=0.85 * (i + 1), amp=1.0, area=50.0),
                           sqi_score=0.9)

    normal_beat  = _make_candidate(ts_sec=0.85 * 6, amp=1.05, area=52.0)
    outlier_beat = _make_candidate(ts_sec=0.85 * 6, amp=4.00, area=200.0)

    vb_n = validator.validate(normal_beat,  sqi_score=0.9)
    vb_o = validator.validate(outlier_beat, sqi_score=0.9)

    print(f"  Normal  beat -> decision={vb_n.decision.value}, "
          f"s_amp={vb_n.score_amplitude:.2f}, s_area={vb_n.score_area:.2f}")
    print(f"  Outlier beat -> decision={vb_o.decision.value}, "
          f"s_amp={vb_o.score_amplitude:.2f}, s_area={vb_o.score_area:.2f}")

    # ── Test 6: Sensor reconnect (Fix #L1) ────────────────────────────────
    print("\n[Test 6] Sensor Reconnect / Buffer Reset (Fix #L1)")
    system3 = PPGPeakDetectionSystem(fs=fs)
    ppg_seg = _generate_synthetic_ppg(fs=fs, duration_sec=5.0, snr_db=25.0)
    system3.boot_calibrate(ppg_seg)
    for start in range(0, len(ppg_seg) - window_n, step_n):
        system3.process_window(ppg_seg[start:start+window_n],
                                window_start_sec=start/fs)
    ibi_before = len(system3.validator._ibi_buffer)
    print(f"  IBI buffer before reconnect: {ibi_before} entries")
    system3.on_sensor_reconnect()
    ibi_after = len(system3.validator._ibi_buffer)
    print(f"  IBI buffer after  reconnect: {ibi_after} entries (should be 0)")
    assert ibi_after == 0, "Buffer not cleared!"

    # ── Test 7: SplitTimestamp precision at 48 h (Fix #L4) ────────────────
    print("\n[Test 7] SplitTimestamp precision at 48 h (Fix #L4)")
    t_48h = 48 * 3600.0   # 172800 s
    ts_a  = SplitTimestamp.from_seconds(t_48h,       fs=fs)
    ts_b  = SplitTimestamp.from_seconds(t_48h + 0.1, fs=fs)
    delta = ts_b.delta_seconds(ts_a, fs=fs)
    print(f"  delta at 48h: {delta:.6f} s  (should be 0.100000)")
    assert abs(delta - 0.1) < 1e-9, f"Precision loss! delta={delta}"

    # ── Test 8: PTT staleness (Fix #L6) ───────────────────────────────────
    print("\n[Test 8] PTT Staleness Guard (Fix #L6)")
    ptt_est = RobustPTTEstimator()
    for i in range(5):
        ptt_est.update(200.0 + i, wall_sec=float(i))
    fresh   = ptt_est.estimate(now_sec=5.0)
    stale   = ptt_est.estimate(now_sec=20.0)   # 15 s gap > 5 s threshold
    print(f"  Fresh estimate  : {fresh}   (should be a number)")
    print(f"  Stale estimate  : {stale}   (should be None)")
    assert fresh is not None
    assert stale is None, "Stale PTT not suppressed!"

    # ── Test 9: _max_sharpness leaky decay (Fix #L3) ──────────────────────
    print("\n[Test 9] Leaky-max sharpness decay (Fix #L3)")
    v2 = BeatValidator(fs=fs)
    # Seed with one huge glitch sharpness
    glitch = _make_candidate(ts_sec=0.85, amp=1.0)
    glitch.peak_sharpness = 1000.0
    v2._score_morphology(glitch)
    s_after_glitch = v2._max_sharpness
    # Now run 1400 normal beats (half-life) — sharpness should decay ~50%
    for i in range(1400):
        normal = _make_candidate(ts_sec=0.85 * (i + 2), amp=1.0)
        normal.peak_sharpness = 0.05
        v2._score_morphology(normal)
    s_after_decay = v2._max_sharpness
    print(f"  Max sharpness after glitch  : {s_after_glitch:.1f}")
    print(f"  Max sharpness after 1400 beats: {s_after_decay:.3f}  "
          f"(should be ~500 = 50% decay)")
    assert s_after_decay < 600, "Leaky-max not decaying!"

    print("\n[Done] All v3 tests completed successfully.")


if __name__ == "__main__":
    run_demo()
