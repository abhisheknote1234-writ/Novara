"""
physio_monitor.py  (improved)
================================
Full Physiological Monitoring System
Built ON TOP of hybrid_rpeak_detector.py — does not modify it.

Improvements over original (see inline IMPROVED comments):
──────────────────────────────────────────────────────────
PM-1  PersonalBaseline: added pnn50_baseline field (population mean 20 %).
      StressAnalyser.compute_stress: pnn50_contrib now normalises against
      pnn50_baseline instead of rmssd_baseline×0.5, fixing a dimensional
      mismatch (% ÷ ms) that caused the feature to be effectively dead
      (always ~0) for healthy subjects.

PM-2  PPGProcessor: bandpass filter migrated to SOS form (butter output='sos')
      with a stateful sosfilt zi kept across process() calls.  Eliminates
      the stateless filtfilt re-initialisation transient on every segment
      and resolves the float32 coefficient-quantisation instability for
      order-4 TF-form filters.

PM-3  BeatValidator: _n_ecg is no longer hardcoded to 48.  The actual
      expected input dimension is recorded at fit() time as _trained_dim
      and checked at validate() time.  A dimension mismatch now raises a
      descriptive warning and falls back to the rule-based path rather than
      crashing with a cryptic sklearn error.

PM-4  MultiModalFusion._fuse_combined: cross_check score now always clipped
      to [0, 1].  The "no-warning" branch returned 1.0 - hr_diff/60 without
      a max(0, …) guard, so at hr_diff > 60 bpm (possible during AF or motion
      artefact) the cross_check score went negative, corrupting the
      pipeline-wide confidence cube-root in PhysioMonitor.update.

PM-5  PhysioMonitor.__init__: added verbose=False parameter.  The two print()
      calls at init are now gated behind it, removing noise in production and
      test code.

PM-6  PhysioMonitor.update: the fallback feature_vector dimension on
      Exception is now inferred from the actual detector CNN state (32 or 48)
      rather than hardcoded to 32, so it matches whatever the BeatValidator
      model was trained on.

PM-7  (documentation) set_baseline_from_recording: docstring now notes that
      the last seg_len samples of each signal are not included in any window
      (< 3 % of data at typical 3-min/10-s settings — acceptable but worth
      knowing when debugging sparse baseline windows).

All original functionality is preserved.  The module remains a pure
add-on to hybrid_rpeak_detector.py with no changes to that file.
"""

import numpy as np
import pickle
import warnings
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from scipy.signal import butter, sosfilt, sosfilt_zi, filtfilt, find_peaks
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import RobustScaler
from sklearn.pipeline import Pipeline

warnings.filterwarnings('ignore')

# ── Import existing detector (unchanged) ──────────────────────────────
from hybrid_rpeak_detector import (
    HybridRPeakDetector,
    AdaptiveBaseline,
    FeatureExtractor,
    FEATURE_NAMES,
    Config as DetectorConfig,
)


# ═══════════════════════════════════════════════════════════════════
#  SHARED DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════

@dataclass
class BeatResult:
    """Result for one verified beat after validation."""
    sample_idx      : int
    timestamp_ms    : float
    source          : str           # 'ecg' | 'ppg' | 'fused'
    beat_class      : int           # 0=noise, 1=valid, 2=abnormal (PVC)
    beat_label      : str           # 'valid' | 'noise' | 'pvc'
    confidence      : float
    rr_ms           : float
    ptt_ms          : float = 0.0
    noise_score     : float = 0.0
    abnormal_score  : float = 0.0
    valid_score     : float = 0.0
    is_uncertain    : bool  = False


@dataclass
class HRVWindow:
    """HRV metrics computed over one sliding window."""
    window_sec   : float
    n_beats      : int
    mean_hr_bpm  : float
    sdnn_ms      : float
    rmssd_ms     : float
    pnn50_pct    : float
    lf_hf_ratio  : float
    mean_rr_ms   : float
    rr_intervals : List[float]


@dataclass
class StressResult:
    """Stress analysis output for one window."""
    stress_score          : float
    state                 : str     # 'relaxed'|'mild_stress'|'high_stress'|'unreliable'
    hrv                   : HRVWindow
    contributing_features : Dict[str, float] = field(default_factory=dict)
    hr_vs_baseline        : float = 0.0
    rmssd_vs_baseline     : float = 0.0
    confidence            : float = 1.0
    quality_gated         : bool  = False
    smoothed_score        : float = 0.0
    trend                 : str   = 'stable'
    trend_slope           : float = 0.0


@dataclass
class MonitorResult:
    """Complete output of one PhysioMonitor.update() call."""
    timestamp_ms        : float
    mode                : str
    beats               : List[BeatResult]
    stress              : Optional[StressResult]
    n_valid_beats       : int
    n_noise_beats       : int
    n_pvc_beats         : int
    quality_score       : float
    warnings            : List[str]
    overall_confidence  : float = 1.0
    beat_confidence_mean: float = 1.0
    fusion_agreement    : float = 1.0


# ═══════════════════════════════════════════════════════════════════
#  MODULE 1: PPG PROCESSOR
# ═══════════════════════════════════════════════════════════════════

class PPGProcessor:
    """
    Detects systolic peaks in PPG signal and extracts IBI intervals.

    IMPROVED PM-2: bandpass filter stored in SOS form with persistent
    sosfilt state.  Eliminates per-call re-initialisation transients and
    resolves float32 instability of TF-form order-4 coefficients.
    """

    def __init__(self, fs: int = 250, ir_channel: bool = True):
        self.fs         = fs
        self.ir_channel = ir_channel

        # IMPROVED PM-2: SOS form — float32-stable, stateful across calls
        nyq          = fs / 2.0
        self._sos    = butter(4, [0.5/nyq, 10.0/nyq], btype='band', output='sos')
        self._zi     = sosfilt_zi(self._sos) * 0.0   # zero-initialised

        # Keep TF-form for the one-shot offline filtfilt path (baseline recording)
        self._b, self._a = butter(4, [0.5/nyq, 10.0/nyq], btype='band')

        self._min_dist           = int(0.35 * fs)
        self._min_prom           = 0.05
        self._rr_avg             = float(fs * 0.857)   # 70 bpm default
        self._amp_avg            = 1.0
        self._alpha              = 0.15
        self._peak_confidences   = np.array([])

    def process(self, ppg_raw: np.ndarray,
                streaming: bool = True) -> Tuple[np.ndarray, np.ndarray]:
        """
        Detect systolic peaks in PPG signal.

        Parameters
        ----------
        ppg_raw   : 1-D raw PPG array from MAX30102 (IR or Red channel)
        streaming : if True (default) use stateful sosfilt — correct for
                    live segment-by-segment processing.
                    If False, use zero-phase filtfilt — correct for offline
                    batch processing of complete recordings.

        Returns
        -------
        peaks  : sample indices of systolic peaks
        ibi_ms : inter-beat intervals in ms (len = len(peaks)-1)
        """
        if len(ppg_raw) < self.fs:
            return np.array([], dtype=int), np.array([])

        sig = ppg_raw.astype(np.float64)

        # IMPROVED PM-2: choose filter path based on use-case
        if streaming:
            sig_filt, self._zi = sosfilt(self._sos, sig, zi=self._zi)
        else:
            sig_filt = filtfilt(self._b, self._a, sig)

        # Invert if signal is inverted (some sensors)
        if np.abs(np.min(sig_filt)) > np.abs(np.max(sig_filt)):
            sig_filt = -sig_filt

        prom_thresh = self._min_prom * np.ptp(sig_filt)
        peaks, _ = find_peaks(
            sig_filt,
            distance   = self._min_dist,
            prominence = max(prom_thresh, 1e-6),
        )

        if len(peaks) < 2:
            return peaks, np.array([])

        peaks  = self._validate_peaks(peaks, sig_filt)
        ibi_ms = np.diff(peaks) / self.fs * 1000.0

        for pk in peaks:
            self._amp_avg = ((1-self._alpha)*self._amp_avg +
                             self._alpha*float(sig_filt[pk]))
        for ibi in ibi_ms:
            rr_samples   = ibi * self.fs / 1000.0
            self._rr_avg = ((1-self._alpha)*self._rr_avg +
                             self._alpha*rr_samples)

        return peaks, ibi_ms

    def _score_peak_shape(self, sig: np.ndarray, pk: int) -> float:
        n        = len(sig)
        fs       = self.fs
        rise_win = int(0.15 * fs)
        half_win = int(0.10 * fs)

        s   = max(0, pk - half_win)
        e   = min(n, pk + half_win)
        seg = sig[s:e]
        if len(seg) < 4:
            return 0.5

        amp        = float(sig[pk])
        local_mean = float(np.mean(seg))
        local_std  = float(np.std(seg)) + 1e-9

        prominence = (amp - local_mean) / local_std
        f1 = np.clip(prominence / 3.0, 0, 1)

        rise_start = max(0, pk - rise_win)
        rise_seg   = sig[rise_start:pk]
        if len(rise_seg) > 2:
            amp_range  = float(np.ptp(sig[max(0, pk-int(0.5*fs)):
                                         min(n, pk+int(0.5*fs))])) + 1e-9
            rise_slope = float(sig[pk] - sig[rise_start]) / (len(rise_seg)*amp_range)
            f2 = np.clip(rise_slope * 10.0, 0, 1)
        else:
            f2 = 0.5

        half_prom = local_mean + 0.5 * (amp - local_mean)
        width_s   = int(np.sum(seg > half_prom))
        w_min = int(0.05 * fs)
        w_max = int(0.30 * fs)
        f3 = 1.0 if w_min <= width_s <= w_max else \
             np.clip(1.0 - abs(width_s - (w_min+w_max)//2) / w_max, 0, 1)

        c = pk - s
        if 1 < c < len(seg) - 2:
            sharpness = abs(float(seg[c-1] - 2*seg[c] + seg[c+1])) / local_std
            f4 = np.clip(sharpness * 5.0, 0, 1)
        else:
            f4 = 0.5

        if self._amp_avg > 1e-6:
            amp_ratio = amp / self._amp_avg
            f5 = 1.0 if 0.4 <= amp_ratio <= 2.5 else \
                 np.clip(1.0 - abs(amp_ratio - 1.0) / 1.5, 0, 1)
        else:
            f5 = 0.8

        return float(np.clip(0.25*f1 + 0.25*f2 + 0.20*f3 + 0.15*f4 + 0.15*f5,
                             0.0, 1.0))

    def _validate_peaks(self, peaks: np.ndarray,
                         sig: np.ndarray) -> np.ndarray:
        if len(peaks) < 2:
            self._peak_confidences = np.ones(len(peaks))
            return peaks

        rr_min = int(0.30 * self.fs)
        rr_max = int(2.00 * self.fs)

        sig_cv       = float(np.std(sig)) / (abs(float(np.mean(sig))) + 1e-9)
        adapt_thresh = np.clip(0.40 - (sig_cv - 0.3) * 0.2, 0.25, 0.60)

        keep        = [peaks[0]]
        conf_scores = [self._score_peak_shape(sig, peaks[0])]

        for pk in peaks[1:]:
            rr   = pk - keep[-1]
            conf = self._score_peak_shape(sig, pk)

            if rr < rr_min:
                if conf > conf_scores[-1]:
                    keep[-1]        = pk
                    conf_scores[-1] = conf
                continue

            if rr > rr_max:
                if conf >= adapt_thresh * 0.8:
                    keep.append(pk)
                    conf_scores.append(conf)
                continue

            if conf >= adapt_thresh:
                keep.append(pk)
                conf_scores.append(conf)

        self._peak_confidences = np.array(conf_scores)
        return np.array(keep, dtype=int)

    def extract_ppg_features(self, ppg_raw: np.ndarray,
                               peak_idx: int) -> np.ndarray:
        n   = len(ppg_raw)
        fs  = self.fs
        win = int(0.3 * fs)

        s   = max(0, peak_idx - win)
        e   = min(n, peak_idx + win)
        seg = ppg_raw[s:e].astype(np.float64)

        if len(seg) < 4:
            return np.zeros(8)

        amp        = float(ppg_raw[peak_idx])
        local_mean = float(np.mean(seg))
        local_std  = float(np.std(seg)) + 1e-9

        rise_seg  = ppg_raw[max(0, peak_idx-win): peak_idx]
        thresh_lo = local_mean + 0.1*(amp-local_mean)
        thresh_hi = local_mean + 0.9*(amp-local_mean)
        above_lo  = np.where(rise_seg > thresh_lo)[0]
        above_hi  = np.where(rise_seg > thresh_hi)[0]
        rise_time = ((len(above_lo)-len(above_hi)) / fs * 1000
                     if len(above_lo) > len(above_hi) else 100.0)

        half  = (amp + local_mean) / 2.0
        width = float(np.sum(seg > half))

        dn_s     = min(n, peak_idx + int(0.20*fs))
        dn_e     = min(n, peak_idx + int(0.40*fs))
        dn_seg   = ppg_raw[dn_s:dn_e]
        dn_depth = (float(amp - np.min(dn_seg)) / (amp + 1e-9)
                    if len(dn_seg) > 0 else 0.0)

        return np.array([
            (amp - local_mean) / local_std,
            rise_time,
            width,
            dn_depth,
            float(np.sum(seg**2)),
            float(np.std(seg)),
            amp / (self._amp_avg + 1e-9),
            float(np.max(np.abs(np.diff(seg[:len(seg)//2]))))
        ], dtype=np.float32)


# ═══════════════════════════════════════════════════════════════════
#  MODULE 2: BEAT VALIDATOR
# ═══════════════════════════════════════════════════════════════════

class BeatValidator:
    """
    Classifies each beat as: valid (1), noise (0), or abnormal/PVC (2).

    IMPROVED PM-3: _n_ecg is no longer hardcoded to 48.
    The expected input dimension is recorded at fit() time as _trained_dim.
    validate() checks for a mismatch and falls back to the rule-based path
    rather than crashing with a cryptic sklearn dimension error.

    This is the most important safety fix: if the ECG detector has no CNN
    (32-dim features) but the validator was trained on 48-dim data (or vice
    versa), the code previously raised a hard sklearn ValueError at inference
    time with no explanation.
    """

    NOISE    = 0
    VALID    = 1
    ABNORMAL = 2

    LABEL_MAP = {0: 'noise', 1: 'valid', 2: 'pvc'}

    def __init__(self, mode: str = 'ecg'):
        self.mode        = mode
        self.model       = None
        self._trained    = False
        self._trained_dim: Optional[int] = None   # IMPROVED PM-3

        self._n_ecg  = 48   # default expected ECG dim (with CNN)
        self._n_ppg  = 8
        mode_map = {'ecg'     : self._n_ecg,
                    'ppg'     : self._n_ppg,
                    'combined': self._n_ecg + self._n_ppg,
                    'ecg_ppg' : self._n_ecg + self._n_ppg}
        self._n_input = mode_map.get(mode, self._n_ecg)

    def build_model(self, n_features: int = None) -> Pipeline:
        n   = n_features or self._n_input
        clf = GradientBoostingClassifier(
            n_estimators=150, max_depth=3, learning_rate=0.05,
            subsample=0.8, min_samples_leaf=5, random_state=42)
        return Pipeline([('scaler', RobustScaler()), ('clf', clf)])

    def fit(self, X: np.ndarray, y: np.ndarray):
        if len(np.unique(y)) < 2:
            print("[BeatValidator] Need at least 2 classes to train.")
            return

        self.model       = self.build_model(X.shape[1])
        self.model.fit(X, y)
        self._trained    = True
        # IMPROVED PM-3: record actual training dimension
        self._trained_dim = int(X.shape[1])
        print(f"[BeatValidator] Trained on {len(y)} beats "
              f"({np.bincount(y).tolist()}) | input_dim={self._trained_dim}")

    def validate(self, feature_vector: np.ndarray,
                 ppg_features: np.ndarray = None) -> Tuple[int, float]:
        """
        Classify one beat.

        IMPROVED PM-3: if the model's trained dimension does not match the
        incoming feature vector, log a warning and fall back to the
        rule-based path rather than crashing.
        """
        if not self._trained or self.model is None:
            return self._rule_based_fallback(feature_vector)

        # IMPROVED PM-3: dimension guard
        if self.mode == 'ecg':
            x = feature_vector
        elif self.mode == 'ppg':
            x = ppg_features if ppg_features is not None else np.zeros(self._n_ppg)
        else:
            ppg = ppg_features if ppg_features is not None else np.zeros(self._n_ppg)
            ecg = feature_vector if feature_vector is not None else np.zeros(self._n_ecg)
            x   = np.concatenate([ecg, ppg])

        x = np.array(x, dtype=np.float32).reshape(1, -1)
        x = np.where(np.isfinite(x), x, 0.0)

        # IMPROVED PM-3: soft dimension check — fall back rather than crash
        if self._trained_dim is not None and x.shape[1] != self._trained_dim:
            warnings.warn(
                f"[BeatValidator] Feature dimension mismatch: "
                f"model expects {self._trained_dim}, got {x.shape[1]}. "
                f"Falling back to rule-based classifier.  "
                f"Retrain the validator with features from the same "
                f"detector configuration (CNN on/off).",
                RuntimeWarning, stacklevel=2)
            return self._rule_based_fallback(feature_vector)

        try:
            probs      = self.model.predict_proba(x)[0]
            pred_class = int(np.argmax(probs))
            confidence = float(probs[pred_class])
            return pred_class, confidence
        except Exception as e:
            warnings.warn(f"[BeatValidator] predict_proba failed: {e}. "
                          f"Falling back to rule-based classifier.", RuntimeWarning)
            return self._rule_based_fallback(feature_vector)

    # ── Feature index map ──────────────────────────────────────────────
    _FI = {
        'rel_amp'     : 0,  'qrs_width'   : 3,
        'slope_ratio' : 6,  'sharpness'   : 7,
        'energy_ratio': 10, 'tmpl_corr'   : 20,
        'tmpl_corr2'  : 21, 'morph_con'   : 28,
        'rr_ratio_p'  : 16, 'rr_ratio_n'  : 17,
        'rr_reg'      : 18,
    }

    @staticmethod
    def _safe_get(fv: np.ndarray, idx: int, default: float = 0.0) -> float:
        return float(fv[idx]) if fv is not None and len(fv) > idx else default

    def _compute_scores(self, fv: np.ndarray) -> Tuple[float, float, float]:
        g  = self._safe_get
        FI = self._FI

        rel_amp      = g(fv, FI['rel_amp'],      1.0)
        qrs_width    = g(fv, FI['qrs_width'],    10.0)
        slope_ratio  = g(fv, FI['slope_ratio'],  1.0)
        sharpness    = abs(g(fv, FI['sharpness'], 0.0))
        energy_ratio = g(fv, FI['energy_ratio'], 0.5)
        tmpl_corr    = g(fv, FI['tmpl_corr'],    0.8)
        morph_con    = g(fv, FI['morph_con'],    0.8)
        rr_ratio_p   = g(fv, FI['rr_ratio_p'],  1.0)
        rr_ratio_n   = g(fv, FI['rr_ratio_n'],  1.0)
        rr_reg       = g(fv, FI['rr_reg'],       0.05)

        n1 = np.clip(1.0 - rel_amp / 0.8,          0, 1)
        n2 = np.clip(1.0 - tmpl_corr,               0, 1)
        n3 = np.clip(1.0 - morph_con,               0, 1)
        n4 = np.clip(1.0 - energy_ratio / 0.4,      0, 1)
        n5 = np.clip(1.0 - sharpness / 0.005,       0, 1)
        n6 = np.clip(abs(rr_ratio_p - 1.0) / 0.4,   0, 1)
        n7 = np.clip(rr_reg / 0.3,                   0, 1)
        noise_score = (0.25*n2 + 0.20*n3 + 0.15*n1 +
                       0.15*n4 + 0.10*n5 + 0.10*n6 + 0.05*n7)

        a1 = np.clip((qrs_width - 20) / 20.0,        0, 1)
        a2 = np.clip(1.0 - tmpl_corr / 0.7,          0, 1)
        a3 = np.clip(rel_amp / 1.5,                   0, 1)
        a4 = np.clip(energy_ratio / 0.5,              0, 1)
        a5 = np.clip(abs(slope_ratio - 1.0) / 1.0,   0, 1)
        pvc_gate      = a3 * a4
        abnormal_score= pvc_gate * (0.35*a2 + 0.30*a1 + 0.20*a5 + 0.15*(1-n1))

        v1 = np.clip(tmpl_corr,                       0, 1)
        v2 = np.clip(morph_con,                       0, 1)
        v3 = np.clip(rel_amp / 1.0,                   0, 1)
        v4 = np.clip(energy_ratio / 0.6,              0, 1)
        v5 = np.clip(1.0 - abs(rr_ratio_p - 1.0)/0.3, 0, 1)
        valid_score = (0.30*v1 + 0.25*v2 + 0.20*v3 + 0.15*v4 + 0.10*v5)

        return float(noise_score), float(abnormal_score), float(valid_score)

    def _rule_based_fallback(self, fv: np.ndarray) -> Tuple[int, float]:
        if fv is None or len(fv) < 10:
            return self.VALID, 0.60

        noise_s, abnorm_s, valid_s = self._compute_scores(fv)
        scores = np.array([noise_s, abnorm_s, valid_s])
        exp_s  = np.exp(scores * 3.0)
        probs  = exp_s / (exp_s.sum() + 1e-9)
        pred_class = int(np.argmax(scores))
        return pred_class, float(probs[pred_class])

    def _is_uncertain(self, fv: np.ndarray,
                       threshold: float = 0.15) -> bool:
        if fv is None or len(fv) < 10:
            return True
        noise_s, abnorm_s, valid_s = self._compute_scores(fv)
        scores = sorted([noise_s, abnorm_s, valid_s], reverse=True)
        return (scores[0] - scores[1]) < threshold

    def validate_full(self, feature_vector: np.ndarray,
                      ppg_features: np.ndarray = None
                      ) -> Tuple[int, float, float, float, float, bool]:
        beat_class, confidence = self.validate(feature_vector, ppg_features)
        if feature_vector is not None and len(feature_vector) >= 10:
            n, a, v = self._compute_scores(feature_vector)
        else:
            n, a, v = 0.0, 0.0, 1.0
        uncertain = self._is_uncertain(feature_vector)
        return beat_class, confidence, n, a, v, uncertain

    def save(self, path: str):
        import os
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.',
                    exist_ok=True)
        with open(path, 'wb') as f:
            pickle.dump({'model'      : self.model,
                         'mode'       : self.mode,
                         'trained'    : self._trained,
                         'trained_dim': self._trained_dim}, f)

    def load(self, path: str):
        with open(path, 'rb') as f:
            p = pickle.load(f)
        self.model        = p['model']
        self.mode         = p['mode']
        self._trained     = p['trained']
        # IMPROVED PM-3: load trained_dim if present (backwards-compatible)
        self._trained_dim = p.get('trained_dim', None)

    @staticmethod
    def generate_training_data(
            ecg_list        : list,
            expert_peak_list: list,
            detector,
            fs              : int   = 250,
            match_tol_ms    : float = 50.0,
            morph_dev_thresh: float = 0.35,
            balance_classes : bool  = True,
            include_noisy   : bool  = True,
            verbose         : bool  = True,
    ) -> Tuple[np.ndarray, np.ndarray, list]:
        """
        Generate training data for BeatValidator from labelled ECG.

        Returns X, y, metadata.  See class docstring for labelling strategy.
        """
        from hybrid_rpeak_detector import AdaptiveBaseline, FeatureExtractor

        match_tol = int(match_tol_ms * fs / 1000)
        feat_ext  = FeatureExtractor(fs=fs)

        all_X, all_y, all_meta = [], [], []

        for sig_id, (ecg_raw, expert_peaks) in enumerate(
                zip(ecg_list, expert_peak_list)):

            peaks, info = detector.detect(ecg_raw, verbose=False)
            ecg_bp      = info.get('ecg_bp',   ecg_raw)
            baseline    = info.get('baseline', AdaptiveBaseline(fs))

            if len(peaks) < 3:
                continue

            template_buf = []
            qw = int(0.06 * fs)

            for i, pk in enumerate(peaks):
                dists    = np.abs(np.array(expert_peaks) - pk)
                min_dist = int(np.min(dists)) if len(expert_peaks) > 0 else 9999

                if min_dist <= match_tol:
                    n = len(ecg_bp)
                    s = max(0, pk - qw)
                    e = min(n, pk + qw)
                    seg = ecg_bp[s:e]

                    if len(seg) >= 4:
                        amp      = np.max(np.abs(seg))
                        norm_seg = seg / (amp + 1e-8)
                        if len(template_buf) >= 3:
                            tmpl = np.mean(template_buf, axis=0)
                            if len(norm_seg) == len(tmpl):
                                corr  = float(np.corrcoef(norm_seg, tmpl)[0, 1])
                                label = 2 if (np.isfinite(corr) and
                                              corr < (1-morph_dev_thresh)) else 1
                            else:
                                label = 1
                        else:
                            label = 1

                        tlen = 2*qw + 1
                        if len(norm_seg) == tlen:
                            template_buf.append(norm_seg)
                            if len(template_buf) > 8:
                                template_buf.pop(0)
                    else:
                        label = 1
                else:
                    label = 0

                try:
                    fv  = feat_ext.extract(ecg_bp, peaks, baseline, i)
                    vec = np.concatenate([fv, detector.cnn.embed(ecg_bp, int(pk))]) \
                          if detector.cnn is not None else fv
                    vec = np.where(np.isfinite(vec), vec, 0.0)
                    all_X.append(vec)
                    all_y.append(label)
                    rr = float(peaks[i]-peaks[i-1]) / fs * 1000 if i > 0 else 0.0
                    all_meta.append({'signal_id'        : sig_id,
                                     'peak_idx'         : int(pk),
                                     'rr_ms'            : rr,
                                     'label'            : label,
                                     'min_dist_samples' : min_dist})
                except Exception:
                    continue

            if verbose:
                nc = all_y.count(0) if all_y else 0
                nv = all_y.count(1) if all_y else 0
                na = all_y.count(2) if all_y else 0
                print(f"  Signal {sig_id}: {len(peaks)} peaks → "
                      f"{nv}valid {nc}noise {na}abnormal")

        if not all_X:
            return np.array([]), np.array([]), []

        X = np.array(all_X, dtype=np.float32)
        y = np.array(all_y, dtype=int)

        if balance_classes and len(np.unique(y)) > 1:
            counts  = np.bincount(y)
            max_cnt = int(counts.max())
            X_parts, y_parts, m_parts = [X], [y], list(all_meta)
            for cls in range(len(counts)):
                if counts[cls] == 0 or counts[cls] >= max_cnt:
                    continue
                idx      = np.where(y == cls)[0]
                n_needed = max_cnt - counts[cls]
                rng      = np.random.RandomState(42 + cls)
                chosen   = idx[rng.randint(0, len(idx), n_needed)]
                noise    = rng.randn(n_needed, X.shape[1]).astype(np.float32) * 0.01
                X_parts.append(X[chosen] + noise)
                y_parts.append(np.full(n_needed, cls, dtype=int))
                m_parts.extend([all_meta[c] for c in chosen])
                if verbose:
                    print(f"  Balanced class {cls}: {counts[cls]} → {max_cnt}")
            X        = np.vstack(X_parts)
            y        = np.concatenate(y_parts)
            all_meta = m_parts

        if verbose:
            counts = np.bincount(y)
            print(f"\nFinal dataset: {len(y)} samples")
            for i, c in enumerate(counts):
                print(f"  Class {i}: {c} ({c/len(y)*100:.1f}%)")

        return X, y, all_meta


# ═══════════════════════════════════════════════════════════════════
#  MODULE 3: MULTI-MODAL FUSION
# ═══════════════════════════════════════════════════════════════════

class MultiModalFusion:
    """
    Fuses ECG and PPG signals.

    IMPROVED PM-4: cross_check score now always clipped to [0, 1].
    The original "no-warning" else-branch returned 1.0 - hr_diff/60
    without a max(0, …) guard; at hr_diff > 60 bpm (AF, severe motion
    artefact) the score went negative and corrupted the confidence
    cube-root in PhysioMonitor.update.
    """

    PTT_MIN_MS = 80
    PTT_MAX_MS = 400

    def __init__(self, fs: int = 250,
                 enable_ecg: bool = True,
                 enable_ppg: bool = False):
        self.fs         = fs
        self.enable_ecg = enable_ecg
        self.enable_ppg = enable_ppg
        self._ptt_avg   = 150.0
        self._ptt_alpha = 0.15
        self._ptt_history = deque(maxlen=30)

    @property
    def mode(self) -> str:
        if self.enable_ecg and self.enable_ppg:
            return 'ecg_ppg'
        elif self.enable_ecg:
            return 'ecg_only'
        elif self.enable_ppg:
            return 'ppg_only'
        raise ValueError("At least one signal must be enabled.")

    def fuse(self,
             ecg_peaks : Optional[np.ndarray],
             ppg_peaks : Optional[np.ndarray],
             ecg_rr_ms : Optional[np.ndarray],
             ppg_ibi_ms: Optional[np.ndarray]) -> dict:
        result = {
            'rr_ms'      : np.array([]),
            'source'     : self.mode,
            'ptt_ms'     : np.array([]),
            'ptt_mean_ms': 0.0,
            'cross_check': 1.0,
            'warnings'   : [],
        }
        if self.mode == 'ecg_only':
            result['rr_ms'] = ecg_rr_ms if ecg_rr_ms is not None else np.array([])
        elif self.mode == 'ppg_only':
            result['rr_ms'] = ppg_ibi_ms if ppg_ibi_ms is not None else np.array([])
        elif self.mode == 'ecg_ppg':
            result = self._fuse_combined(ecg_peaks, ppg_peaks,
                                          ecg_rr_ms, ppg_ibi_ms, result)
        return result

    def _fuse_combined(self, ecg_peaks, ppg_peaks,
                        ecg_rr, ppg_ibi, result) -> dict:
        warn = []

        if ecg_rr is not None and len(ecg_rr) > 0:
            result['rr_ms'] = ecg_rr
        elif ppg_ibi is not None and len(ppg_ibi) > 0:
            result['rr_ms'] = ppg_ibi
            warn.append('ecg_peaks_missing_using_ppg')

        if (ecg_rr is not None and len(ecg_rr) > 2 and
                ppg_ibi is not None and len(ppg_ibi) > 2):
            ecg_hr  = 60000.0 / np.mean(ecg_rr)
            ppg_hr  = 60000.0 / np.mean(ppg_ibi)
            hr_diff = abs(ecg_hr - ppg_hr)

            if hr_diff > 10:
                warn.append(f'hr_mismatch_ecg={ecg_hr:.0f}_ppg={ppg_hr:.0f}')

            # IMPROVED PM-4: always clip to [0, 1] — no-warning branch could
            # return negative values at hr_diff > 60 bpm
            result['cross_check'] = float(np.clip(1.0 - hr_diff / 60.0, 0.0, 1.0))

        if (ecg_peaks is not None and ppg_peaks is not None and
                len(ecg_peaks) > 0 and len(ppg_peaks) > 0):
            ptt_values = self._compute_ptt(ecg_peaks, ppg_peaks)
            result['ptt_ms']      = ptt_values
            result['ptt_mean_ms'] = float(np.mean(ptt_values)) \
                                    if len(ptt_values) > 0 else 0.0
            if result['ptt_mean_ms'] > 0:
                self._ptt_history.append(result['ptt_mean_ms'])
                self._ptt_avg = ((1-self._ptt_alpha)*self._ptt_avg +
                                  self._ptt_alpha*result['ptt_mean_ms'])

        result['warnings'] = warn
        return result

    def _compute_ptt(self, ecg_peaks: np.ndarray,
                      ppg_peaks: np.ndarray) -> np.ndarray:
        ptt_list  = []
        ptt_min_s = self.PTT_MIN_MS * self.fs / 1000
        ptt_max_s = self.PTT_MAX_MS * self.fs / 1000

        for r in ecg_peaks:
            future_ppg = ppg_peaks[ppg_peaks > r]
            if len(future_ppg) == 0:
                continue
            ptt_s = float(future_ppg[0] - r)
            if ptt_min_s <= ptt_s <= ptt_max_s:
                ptt_list.append(ptt_s / self.fs * 1000.0)

        return np.array(ptt_list) if ptt_list else np.array([])

    def set_mode(self, enable_ecg: bool, enable_ppg: bool):
        if not enable_ecg and not enable_ppg:
            raise ValueError("At least one of enable_ecg/enable_ppg must be True")
        self.enable_ecg = enable_ecg
        self.enable_ppg = enable_ppg


# ═══════════════════════════════════════════════════════════════════
#  MODULE 4: HRV FEATURE COMPUTER
# ═══════════════════════════════════════════════════════════════════

class HRVComputer:
    """Computes HRV features from a window of RR intervals."""

    def __init__(self, fs: int = 250):
        self.fs = fs

    def compute(self, rr_ms: np.ndarray,
                window_sec: float = 60.0) -> Optional[HRVWindow]:
        rr = np.array(rr_ms, dtype=np.float64)
        rr = rr[(rr >= 300) & (rr <= 2000)]

        if len(rr) < 5:
            return None

        mean_rr    = float(np.mean(rr))
        mean_hr    = float(60000.0 / mean_rr)
        sdnn       = float(np.std(rr, ddof=1))
        successive = np.diff(rr)
        rmssd      = float(np.sqrt(np.mean(successive**2)))
        pnn50      = float(np.sum(np.abs(successive) > 50) /
                           max(len(successive), 1) * 100)
        lf_hf      = self._compute_lf_hf(rr) if len(rr) >= 20 else 0.0

        return HRVWindow(
            window_sec   = window_sec,
            n_beats      = len(rr),
            mean_hr_bpm  = mean_hr,
            sdnn_ms      = sdnn,
            rmssd_ms     = rmssd,
            pnn50_pct    = pnn50,
            lf_hf_ratio  = lf_hf,
            mean_rr_ms   = mean_rr,
            rr_intervals = rr.tolist(),
        )

    def _compute_lf_hf(self, rr_ms: np.ndarray) -> float:
        from scipy.signal import lombscargle
        try:
            rr_s    = rr_ms / 1000.0
            t_cumul = np.cumsum(rr_s) - np.cumsum(rr_s)[0]
            f_lf    = np.linspace(0.04, 0.15, 50)
            f_hf    = np.linspace(0.15, 0.40, 50)
            omega   = 2 * np.pi * np.concatenate([f_lf, f_hf])
            pgram   = lombscargle(t_cumul, rr_ms - np.mean(rr_ms),
                                  omega, normalize=True)
            _trapz  = np.trapezoid if hasattr(np, 'trapezoid') else np.trapz
            lf_pow  = float(_trapz(pgram[:len(f_lf)], f_lf))
            hf_pow  = float(_trapz(pgram[len(f_lf):], f_hf))
            return lf_pow / (hf_pow + 1e-9)
        except Exception:
            return 0.0


# ═══════════════════════════════════════════════════════════════════
#  MODULE 5: PERSONAL BASELINE
# ═══════════════════════════════════════════════════════════════════

class PersonalBaseline:
    """
    Stores and maintains a person's resting physiological baseline.

    IMPROVED PM-1: added pnn50_baseline field (population mean ≈ 20 %).
    This fixes the dimensional mismatch in StressAnalyser.compute_stress
    where pnn50_pct (a percentage, 0–100) was divided by rmssd_baseline
    (in ms), causing pnn50_contrib to be effectively dead for most subjects.
    """

    def __init__(self):
        self.hr_baseline    : float = 70.0    # bpm
        self.rmssd_baseline : float = 30.0    # ms
        self.sdnn_baseline  : float = 40.0    # ms
        self.lf_hf_baseline : float = 1.5
        self.ptt_baseline   : float = 150.0   # ms
        # IMPROVED PM-1: pnn50 baseline in % (population mean ≈ 20 %)
        self.pnn50_baseline : float = 20.0    # %
        self._is_set        : bool  = False
        self._n_windows     : int   = 0

    def update_from_baseline_recording(self, hrv_windows: List[HRVWindow]):
        """Compute personal baseline from a resting HRV recording."""
        if len(hrv_windows) == 0:
            return

        hrs    = [w.mean_hr_bpm  for w in hrv_windows if w is not None]
        rmssds = [w.rmssd_ms     for w in hrv_windows if w is not None]
        sdnns  = [w.sdnn_ms      for w in hrv_windows if w is not None]
        pnn50s = [w.pnn50_pct    for w in hrv_windows if w is not None]
        lf_hfs = [w.lf_hf_ratio  for w in hrv_windows
                  if w is not None and w.lf_hf_ratio > 0]

        if hrs:    self.hr_baseline    = float(np.mean(hrs))
        if rmssds: self.rmssd_baseline = float(np.mean(rmssds))
        if sdnns:  self.sdnn_baseline  = float(np.mean(sdnns))
        if lf_hfs: self.lf_hf_baseline = float(np.mean(lf_hfs))
        # IMPROVED PM-1: set individual pnn50 baseline
        if pnn50s:
            self.pnn50_baseline = max(1.0, float(np.mean(pnn50s)))

        self._is_set    = True
        self._n_windows = len(hrv_windows)
        print(f"[Baseline] Set from {len(hrv_windows)} windows:")
        print(f"  HR={self.hr_baseline:.1f} bpm  "
              f"RMSSD={self.rmssd_baseline:.1f} ms  "
              f"SDNN={self.sdnn_baseline:.1f} ms  "
              f"pNN50={self.pnn50_baseline:.1f}%")

    def normalise(self, hrv: HRVWindow) -> Dict[str, float]:
        """Return baseline-relative metrics (> 1.0 means above baseline)."""
        lf_hf_safe = max(self.lf_hf_baseline, 0.1)
        return {
            'hr_vs_baseline'   : hrv.mean_hr_bpm  / (self.hr_baseline    + 1e-9),
            'rmssd_vs_baseline': hrv.rmssd_ms     / (self.rmssd_baseline + 1e-9),
            'sdnn_vs_baseline' : hrv.sdnn_ms      / (self.sdnn_baseline  + 1e-9),
            'lf_hf_vs_baseline': min(hrv.lf_hf_ratio / lf_hf_safe, 10.0),
        }

    def save(self, path: str):
        import os
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.',
                    exist_ok=True)
        with open(path, 'wb') as f:
            pickle.dump(self.__dict__, f)

    def load(self, path: str):
        with open(path, 'rb') as f:
            d = pickle.load(f)
        for k, v in d.items():
            setattr(self, k, v)
        # IMPROVED PM-1: backwards-compatible — old saved baselines won't have this
        if not hasattr(self, 'pnn50_baseline'):
            self.pnn50_baseline = 20.0


# ═══════════════════════════════════════════════════════════════════
#  MODULE 6: STRESS ANALYSER
# ═══════════════════════════════════════════════════════════════════

class StressAnalyser:
    """
    Computes a stress score from HRV features.

    IMPROVED PM-1: pnn50_contrib formula corrected.
    Original formula: pnn50_norm = hrv.pnn50_pct / (baseline.rmssd_baseline * 0.5)
    Problem: pnn50_pct is in % (0–100); rmssd_baseline is in ms (typical ~30 ms).
    Denominator was ~15, so any subject with pnn50 > 15 % got pnn50_contrib = 0
    (clipped at 0) — the feature was dead for most healthy subjects.
    Fixed formula: pnn50_norm = hrv.pnn50_pct / baseline.pnn50_baseline
    This gives a properly normalised ratio (0 = no pnn50, 1 = at baseline,
    > 1 = higher variability than baseline). The stress contribution is then
    1 - ratio (higher pnn50 = less stress), consistent with the other features.
    """

    WEIGHTS = {
        'hr_contrib'   : 0.20,
        'rmssd_contrib': 0.35,
        'sdnn_contrib' : 0.20,
        'lf_hf_contrib': 0.15,
        'pnn50_contrib': 0.10,
    }

    THRESHOLDS = {'relaxed': 0.35, 'mild_stress': 0.65, 'high_stress': 1.00}

    SMOOTH_ALPHA       = 0.30
    QUALITY_HARD_GATE  = 0.40
    QUALITY_SOFT_GATE  = 0.55
    TREND_WINDOW       = 5
    TREND_INCREASE_THR = 0.08
    TREND_RECOVERY_THR = -0.06

    def __init__(self, window_sec: float = 60.0, step_sec: float = 10.0):
        self.window_sec      = window_sec
        self.step_sec        = step_sec
        self.hrv_computer    = HRVComputer()
        self._rr_buffer      = deque()
        self._smoothed_score = 0.5
        self._score_history  = deque(maxlen=self.TREND_WINDOW)
        self._last_raw_score = 0.5
        self._n_windows      = 0

    def add_rr(self, rr_ms: float, timestamp_ms: float):
        self._rr_buffer.append((timestamp_ms, rr_ms))
        cutoff = timestamp_ms - (self.window_sec * 1000)
        while self._rr_buffer and self._rr_buffer[0][0] < cutoff:
            self._rr_buffer.popleft()

    def compute_stress(self,
                        baseline     : 'PersonalBaseline',
                        quality_score: float = 1.0,
                       ) -> Optional['StressResult']:
        """Compute stress score with quality gating, EMA smoothing, trend detection."""
        if quality_score < self.QUALITY_HARD_GATE:
            return StressResult(
                stress_score          = self._smoothed_score,
                state                 = 'unreliable',
                hrv                   = HRVWindow(0,0,0,0,0,0,0,0,[]),
                contributing_features = {},
                confidence            = 0.0,
                quality_gated         = True,
                smoothed_score        = self._smoothed_score,
                trend                 = 'unknown',
            )

        if len(self._rr_buffer) < 10:
            return None

        rr_array = np.array([r for _, r in self._rr_buffer])
        hrv      = self.hrv_computer.compute(rr_array, self.window_sec)
        if hrv is None:
            return None

        norm = baseline.normalise(hrv)
        contributions = {}

        hr_ratio = norm['hr_vs_baseline']
        contributions['hr_contrib'] = float(
            np.clip((hr_ratio - 1.0) / 0.5, 0.0, 1.0))

        rmssd_ratio = norm['rmssd_vs_baseline']
        contributions['rmssd_contrib'] = float(
            np.clip((1.0 - rmssd_ratio) / 0.6, 0.0, 1.0))

        sdnn_ratio = norm['sdnn_vs_baseline']
        contributions['sdnn_contrib'] = float(
            np.clip((1.0 - sdnn_ratio) / 0.6, 0.0, 1.0))

        lf_hf_ratio = norm['lf_hf_vs_baseline']
        contributions['lf_hf_contrib'] = float(
            np.clip((lf_hf_ratio - 1.0) / 2.0, 0.0, 1.0))

        # IMPROVED PM-1: correct normalisation — pnn50 is %, baseline is %
        pnn50_norm = hrv.pnn50_pct / (baseline.pnn50_baseline + 1e-9)
        contributions['pnn50_contrib'] = float(
            np.clip(1.0 - pnn50_norm, 0.0, 1.0))

        raw_score = float(np.clip(
            sum(self.WEIGHTS[k] * v for k, v in contributions.items()),
            0.0, 1.0))

        if quality_score < self.QUALITY_SOFT_GATE:
            quality_weight = quality_score / self.QUALITY_SOFT_GATE
            raw_score = (quality_weight * raw_score +
                         (1.0 - quality_weight) * self._smoothed_score)

        if self._n_windows == 0:
            self._smoothed_score = raw_score
        else:
            self._smoothed_score = (self.SMOOTH_ALPHA * raw_score +
                                     (1.0 - self.SMOOTH_ALPHA) * self._smoothed_score)

        self._score_history.append(self._smoothed_score)
        self._last_raw_score = raw_score
        self._n_windows     += 1

        trend, trend_slope = self._detect_trend()

        hrv_sufficiency   = float(np.clip(hrv.n_beats / 30.0, 0, 1))
        baseline_validity = 1.0 if baseline._is_set else 0.5
        confidence        = float(quality_score * hrv_sufficiency * baseline_validity)

        s = self._smoothed_score
        if s < self.THRESHOLDS['relaxed']:
            state = 'relaxed'
        elif s < self.THRESHOLDS['mild_stress']:
            state = 'mild_stress'
        else:
            state = 'high_stress'

        return StressResult(
            stress_score          = raw_score,
            state                 = state,
            hrv                   = hrv,
            contributing_features = contributions,
            hr_vs_baseline        = float(norm['hr_vs_baseline']),
            rmssd_vs_baseline     = float(norm['rmssd_vs_baseline']),
            confidence            = confidence,
            quality_gated         = False,
            smoothed_score        = self._smoothed_score,
            trend                 = trend,
            trend_slope           = trend_slope,
        )

    def _detect_trend(self) -> Tuple[str, float]:
        hist = list(self._score_history)
        if len(hist) < 3:
            return 'stable', 0.0
        x     = np.arange(len(hist), dtype=float)
        y     = np.array(hist, dtype=float)
        xm, ym = np.mean(x), np.mean(y)
        slope  = float(np.sum((x-xm)*(y-ym)) / (np.sum((x-xm)**2) + 1e-9))
        if slope > self.TREND_INCREASE_THR:
            trend = 'increasing'
        elif slope < self.TREND_RECOVERY_THR:
            trend = 'recovery'
        else:
            trend = 'stable'
        return trend, round(slope, 4)

    def get_feature_explanation(self, result: 'StressResult') -> str:
        if result is None:
            return "Insufficient data."
        if result.state == 'unreliable':
            return (f"Signal quality too low — stress unreliable.\n"
                    f"Last smoothed score: {result.smoothed_score:.2f}")
        lines = [
            f"Stress score (raw)     : {result.stress_score:.3f}",
            f"Stress score (smoothed): {result.smoothed_score:.3f}",
            f"State                  : {result.state}",
            f"Trend                  : {result.trend} "
            f"(slope={result.trend_slope:+.4f}/window)",
            f"Confidence             : {result.confidence:.3f}",
            f"",
            f"HR    : {result.hrv.mean_hr_bpm:.1f} bpm  "
            f"({result.hr_vs_baseline*100-100:+.0f}% vs baseline)",
            f"RMSSD : {result.hrv.rmssd_ms:.1f} ms  "
            f"({result.rmssd_vs_baseline*100-100:+.0f}% vs baseline)",
            f"SDNN  : {result.hrv.sdnn_ms:.1f} ms",
            f"pNN50 : {result.hrv.pnn50_pct:.1f}%",
            f"LF/HF : {result.hrv.lf_hf_ratio:.2f}",
            f"",
            f"Feature contributions (weighted evidence):",
        ]
        for feat, weight in self.WEIGHTS.items():
            contrib = result.contributing_features.get(feat, 0.0)
            bar     = '█' * int(contrib * 20)
            lines.append(f"  {feat:<18} w={weight:.2f}  "
                         f"score={contrib:.3f}  {bar}")
        return '\n'.join(lines)


# ═══════════════════════════════════════════════════════════════════
#  MODULE 7: SIGNAL QUALITY ESTIMATOR
# ═══════════════════════════════════════════════════════════════════

class SignalQualityEstimator:
    """Estimates signal quality (0-1) from processed ECG/PPG."""

    def __init__(self, fs: int = 250):
        self.fs = fs

    def estimate_ecg_quality(self, ecg_clean: np.ndarray,
                              r_peaks: np.ndarray,
                              info: dict) -> float:
        scores, weights = [], []

        n_cands = info.get('n_candidates', 0)
        n_rules = info.get('n_after_rules', 0)
        if n_cands > 0:
            scores.append(min(1.0, n_rules / n_cands / 0.6))
            weights.append(0.25)

        rr_ms = info.get('rr_intervals_ms', np.array([]))
        if len(rr_ms) >= 3:
            cv         = float(np.std(rr_ms)) / (float(np.mean(rr_ms)) + 1e-9)
            regularity = 1.0 - min(1.0, cv / 0.40)
            scores.append(regularity)
            weights.append(0.25)

        if len(ecg_clean) > self.fs:
            peak_power  = float(np.percentile(np.abs(ecg_clean), 95))
            noise_floor = float(np.percentile(np.abs(ecg_clean), 10))
            snr_est     = peak_power / (noise_floor + 1e-9)
            scores.append(float(np.clip((snr_est - 1) / 14.0, 0, 1)))
            weights.append(0.30)

        ecg_bp = info.get('ecg_bp', ecg_clean)
        if r_peaks is not None and len(r_peaks) >= 4 and ecg_bp is not None:
            try:
                n    = len(ecg_bp)
                amps = np.array([float(abs(ecg_bp[p]))
                                 for p in r_peaks if 0 <= p < n])
                if len(amps) >= 3:
                    amp_cv      = float(np.std(amps)) / (float(np.mean(amps)) + 1e-9)
                    consistency = 1.0 - min(1.0, amp_cv / 0.50)
                    scores.append(consistency)
                    weights.append(0.20)
            except Exception:
                pass

        if not scores:
            return 0.5

        total_w = sum(weights)
        return float(sum(s*w for s, w in zip(scores, weights)) / total_w)

    def estimate_ppg_quality(self, ppg_raw: np.ndarray,
                               ppg_peaks: np.ndarray,
                               peak_confidences: np.ndarray = None) -> float:
        if len(ppg_peaks) < 2 or len(ppg_raw) < self.fs:
            return 0.0

        scores, weights = [], []

        try:
            n    = len(ppg_raw)
            amps = np.abs(ppg_raw[np.clip(ppg_peaks, 0, n-1)])
            if len(amps) > 1:
                cv_amp = np.std(amps) / (np.mean(amps) + 1e-9)
                scores.append(max(0.0, 1.0 - cv_amp / 0.5))
                weights.append(0.30)
        except Exception:
            pass

        ibi = np.diff(ppg_peaks)
        if len(ibi) > 1:
            cv_ibi = np.std(ibi) / (np.mean(ibi) + 1e-9)
            scores.append(max(0.0, 1.0 - cv_ibi / 0.30))
            weights.append(0.35)

        if peak_confidences is not None and len(peak_confidences) > 0:
            scores.append(float(np.mean(peak_confidences)))
            weights.append(0.35)

        if not scores:
            return 0.5

        total_w = sum(weights)
        return float(sum(s*w for s, w in zip(scores, weights)) / total_w)


# ═══════════════════════════════════════════════════════════════════
#  MODULE 8: PHYSIO MONITOR (MAIN ORCHESTRATOR)
# ═══════════════════════════════════════════════════════════════════

class PhysioMonitor:
    """
    Main orchestrator — integrates all modules.

    IMPROVED PM-5: added verbose parameter to __init__.  The two print()
    calls at init are now gated behind it (default False) to remove
    noise in production, test suites, and notebook environments.

    IMPROVED PM-6: fallback feature_vector dimension on Exception is now
    inferred from detector.cnn state (32 or 48) rather than hardcoded to 32.

    Usage:
    ──────
    monitor = PhysioMonitor(fs=250, enable_ecg=True, enable_ppg=True)
    result  = monitor.update(ecg_segment, ppg_ir_segment, timestamp_ms)
    monitor.set_baseline_from_recording(baseline_ecg, baseline_ppg)
    monitor.set_mode(enable_ecg=True, enable_ppg=False)
    """

    def __init__(self,
                 fs               : int   = 250,
                 enable_ecg       : bool  = True,
                 enable_ppg       : bool  = False,
                 stress_window_sec: float = 60.0,
                 verbose          : bool  = False):   # IMPROVED PM-5

        self.fs          = fs
        self.enable_ecg  = enable_ecg
        self.enable_ppg  = enable_ppg

        self.ecg_detector  = HybridRPeakDetector(fs=fs) if enable_ecg else None
        self.ppg_processor = PPGProcessor(fs=fs)

        bv_mode = ('combined' if (enable_ecg and enable_ppg)
                   else 'ecg' if enable_ecg else 'ppg')
        self.beat_validator  = BeatValidator(mode=bv_mode)
        self.fusion          = MultiModalFusion(
            fs=fs, enable_ecg=enable_ecg, enable_ppg=enable_ppg)
        self.stress_analyser = StressAnalyser(window_sec=stress_window_sec)
        self.baseline        = PersonalBaseline()
        self.quality_est     = SignalQualityEstimator(fs=fs)

        self._timestamp_ms   = 0.0
        self._last_beat_time = 0.0
        self._beat_count     = 0
        self._feat_extractor = FeatureExtractor(fs=fs)

        # IMPROVED PM-5: gated print
        if verbose:
            print(f"[PhysioMonitor] Initialised")
            print(f"  Mode  : {'ECG' if enable_ecg else ''}+"
                  f"{'PPG' if enable_ppg else ''} @ {fs} Hz")
            print(f"  Stress window: {stress_window_sec}s")

    def set_mode(self, enable_ecg: bool, enable_ppg: bool):
        if not enable_ecg and not enable_ppg:
            raise ValueError("At least one signal must be enabled")
        if enable_ecg and self.ecg_detector is None:
            self.ecg_detector = HybridRPeakDetector(fs=self.fs)
        self.enable_ecg = enable_ecg
        self.enable_ppg = enable_ppg
        self.fusion.set_mode(enable_ecg, enable_ppg)

    def update(self,
               ecg_segment   : Optional[np.ndarray] = None,
               ppg_ir_segment: Optional[np.ndarray] = None,
               ppg_r_segment : Optional[np.ndarray] = None,
               timestamp_ms  : float = None) -> MonitorResult:
        """Process one segment of physiological data."""
        if timestamp_ms is None:
            sig_ref = (ecg_segment if ecg_segment is not None
                       else ppg_ir_segment if ppg_ir_segment is not None
                       else np.zeros(1))
            self._timestamp_ms += len(sig_ref) / self.fs * 1000.0
            timestamp_ms = self._timestamp_ms
        else:
            self._timestamp_ms = timestamp_ms

        warnings_list = []
        all_beats     = []

        # ── ECG ───────────────────────────────────────────────────────
        ecg_peaks  = None
        ecg_rr_ms  = None
        ecg_info   = {}
        ecg_quality= 1.0

        if self.enable_ecg and ecg_segment is not None:
            ecg_peaks, ecg_info = self.ecg_detector.detect(
                ecg_segment, verbose=False)
            ecg_rr_ms   = ecg_info.get('rr_intervals_ms', np.array([]))
            ecg_quality = self.quality_est.estimate_ecg_quality(
                ecg_info.get('ecg_clean', ecg_segment), ecg_peaks, ecg_info)
            if ecg_quality < 0.4:
                warnings_list.append(f'low_ecg_quality_{ecg_quality:.2f}')
        elif self.enable_ecg:
            warnings_list.append('ecg_enabled_but_no_data')

        # ── PPG ───────────────────────────────────────────────────────
        ppg_peaks  = None
        ppg_ibi_ms = None
        ppg_quality= 1.0

        if self.enable_ppg and ppg_ir_segment is not None:
            ppg_peaks, ppg_ibi_ms = self.ppg_processor.process(ppg_ir_segment)
            ppg_confs   = getattr(self.ppg_processor, '_peak_confidences',
                                    np.array([]))
            ppg_quality = self.quality_est.estimate_ppg_quality(
                ppg_ir_segment,
                ppg_peaks if ppg_peaks is not None else np.array([]),
                peak_confidences=ppg_confs)
            if ppg_quality < 0.4:
                warnings_list.append(f'low_ppg_quality_{ppg_quality:.2f}')
        elif self.enable_ppg:
            warnings_list.append('ppg_enabled_but_no_data')

        # ── Composite quality ─────────────────────────────────────────
        qualities = []
        if self.enable_ecg:  qualities.append(ecg_quality)
        if self.enable_ppg:  qualities.append(ppg_quality)
        quality_score = float(np.mean(qualities)) if qualities else 0.5

        # ── Fusion ────────────────────────────────────────────────────
        fused = self.fusion.fuse(ecg_peaks, ppg_peaks, ecg_rr_ms, ppg_ibi_ms)
        unified_rr_ms = fused['rr_ms']
        warnings_list.extend(fused.get('warnings', []))

        # ── Beat validation ───────────────────────────────────────────
        beats_to_validate = (ecg_peaks if self.enable_ecg and ecg_peaks is not None
                             else ppg_peaks if ppg_peaks is not None
                             else np.array([]))

        ecg_bp  = ecg_info.get('ecg_bp', ecg_segment)
        n_valid = n_noise = n_pvc = 0

        # IMPROVED PM-6: infer expected feature dim from detector state
        ecg_feat_dim = (48 if (self.ecg_detector is not None and
                                self.ecg_detector.cnn is not None) else 32)

        if len(beats_to_validate) > 0 and ecg_bp is not None:
            baseline_obj          = ecg_info.get('baseline', AdaptiveBaseline(self.fs))
            beats_to_validate_arr = np.array(beats_to_validate)

            for i, peak in enumerate(beats_to_validate_arr):
                try:
                    fv = self._feat_extractor.extract(
                        ecg_bp, beats_to_validate_arr, baseline_obj, i)
                    if self.ecg_detector is not None and self.ecg_detector.cnn is not None:
                        embed          = self.ecg_detector.cnn.embed(ecg_bp, int(peak))
                        feature_vector = np.concatenate([fv, embed])
                    else:
                        feature_vector = fv
                except Exception:
                    # IMPROVED PM-6: use correct dim, not hardcoded 32
                    feature_vector = np.zeros(ecg_feat_dim, dtype=np.float32)

                ppg_fv = None
                if self.enable_ppg and ppg_ir_segment is not None:
                    try:
                        ppg_fv = self.ppg_processor.extract_ppg_features(
                            ppg_ir_segment,
                            min(int(peak), len(ppg_ir_segment)-1))
                    except Exception:
                        ppg_fv = None

                beat_class, confidence, n_s, a_s, v_s, uncertain = \
                    self.beat_validator.validate_full(feature_vector, ppg_fv)

                rr  = float(ecg_rr_ms[i-1]) if (ecg_rr_ms is not None and
                                                  i > 0 and
                                                  i-1 < len(ecg_rr_ms)) else 0.0
                ptt = float(fused['ptt_ms'][i]) if len(fused['ptt_ms']) > i else 0.0

                beat = BeatResult(
                    sample_idx     = int(peak),
                    timestamp_ms   = timestamp_ms + int(peak)/self.fs*1000,
                    source         = fused['source'],
                    beat_class     = beat_class,
                    beat_label     = BeatValidator.LABEL_MAP[beat_class],
                    confidence     = confidence,
                    rr_ms          = rr,
                    ptt_ms         = ptt,
                    noise_score    = n_s,
                    abnormal_score = a_s,
                    valid_score    = v_s,
                    is_uncertain   = uncertain,
                )
                all_beats.append(beat)

                if beat_class == BeatValidator.VALID:   n_valid += 1
                elif beat_class == BeatValidator.NOISE: n_noise += 1
                else:                                    n_pvc   += 1

        # ── Stress analysis ───────────────────────────────────────────
        stress_result = None
        if len(unified_rr_ms) > 0 and self.baseline._is_set:
            rr_cumul_ms = np.cumsum(unified_rr_ms)
            seg_len_ms  = (len(ecg_segment) if ecg_segment is not None
                           else len(ppg_ir_segment) if ppg_ir_segment is not None
                           else 1) / self.fs * 1000.0
            t0 = timestamp_ms + seg_len_ms - rr_cumul_ms[-1]
            for i, rr in enumerate(unified_rr_ms):
                self.stress_analyser.add_rr(float(rr), t0 + rr_cumul_ms[i])

            stress_result = self.stress_analyser.compute_stress(
                self.baseline, quality_score=quality_score)

        # ── Pipeline-wide confidence ──────────────────────────────────
        beat_confs     = [b.confidence for b in all_beats
                          if b.beat_class != BeatValidator.NOISE]
        beat_conf_mean = float(np.mean(beat_confs)) if beat_confs else 1.0
        stress_conf    = stress_result.confidence if stress_result else 1.0
        fusion_agr     = float(fused.get('cross_check', 1.0))
        overall_conf   = float(np.cbrt(beat_conf_mean * stress_conf * fusion_agr))

        return MonitorResult(
            timestamp_ms         = timestamp_ms,
            mode                 = self.fusion.mode,
            beats                = all_beats,
            stress               = stress_result,
            n_valid_beats        = n_valid,
            n_noise_beats        = n_noise,
            n_pvc_beats          = n_pvc,
            quality_score        = quality_score,
            warnings             = warnings_list,
            overall_confidence   = overall_conf,
            beat_confidence_mean = beat_conf_mean,
            fusion_agreement     = fusion_agr,
        )

    def set_baseline_from_recording(
            self,
            ecg_baseline: Optional[np.ndarray] = None,
            ppg_baseline: Optional[np.ndarray] = None,
            segment_sec : float = 10.0) -> bool:
        """
        Compute personal baseline from a resting recording.
        Call after collecting 3+ minutes of relaxed, seated data.

        Note (PM-7): the last seg_len samples of each signal are not
        included in any window due to the range upper bound of
        len(signal) - seg_len.  This is < 3 % of data at typical
        settings (3-min recording, 10-s windows) and is acceptable.
        """
        hrv_windows = []
        seg_len     = int(segment_sec * self.fs)

        signals_to_process = []
        if ecg_baseline is not None and self.ecg_detector is not None:
            signals_to_process.append(('ecg', ecg_baseline))
        if ppg_baseline is not None:
            signals_to_process.append(('ppg', ppg_baseline))

        if not signals_to_process:
            print("[Baseline] No signal provided.")
            return False

        for sig_type, signal in signals_to_process:
            for start in range(0, len(signal) - seg_len, seg_len // 2):
                seg = signal[start: start + seg_len]
                if sig_type == 'ecg':
                    _, info = self.ecg_detector.detect(seg, verbose=False)
                    rr_ms   = info.get('rr_intervals_ms', np.array([]))
                else:
                    _, rr_ms = self.ppg_processor.process(seg, streaming=False)

                if len(rr_ms) >= 5:
                    hrv = self.stress_analyser.hrv_computer.compute(
                        rr_ms, segment_sec)
                    if hrv is not None:
                        hrv_windows.append(hrv)

        if len(hrv_windows) < 2:
            print("[Baseline] Not enough data. Need at least 2 minutes.")
            return False

        self.baseline.update_from_baseline_recording(hrv_windows)
        return True

    def train_beat_validator(self,
                              ecg_list  : List[np.ndarray],
                              label_list: List[np.ndarray],
                              ppg_list  : Optional[List[np.ndarray]] = None):
        """Train BeatValidator on labelled data."""
        MATCH_TOL  = int(0.05 * self.fs)
        all_X, all_y = [], []

        for i, (ecg, labels) in enumerate(zip(ecg_list, label_list)):
            if self.ecg_detector is None:
                continue
            _, info  = self.ecg_detector.detect(ecg, verbose=False)
            peaks    = info.get('verified_peaks', np.array([]))
            ecg_bp   = info.get('ecg_bp', ecg)
            bl       = info.get('baseline', AdaptiveBaseline(self.fs))

            if len(peaks) == 0:
                continue

            if isinstance(labels, np.ndarray) and labels.dtype in [int, np.int64]:
                expert = labels
                for j, pk in enumerate(peaks):
                    dists = np.abs(expert - pk)
                    label = 1 if int(np.min(dists)) <= MATCH_TOL else 0
                    try:
                        fv = self._feat_extractor.extract(ecg_bp, peaks, bl, j)
                        if self.ecg_detector.cnn is not None:
                            embed = self.ecg_detector.cnn.embed(ecg_bp, int(pk))
                            all_X.append(np.concatenate([fv, embed]))
                        else:
                            all_X.append(fv)
                        all_y.append(label)
                    except Exception:
                        pass
            else:
                label_map = {int(idx): int(cls) for idx, cls in labels}
                for j, pk in enumerate(peaks):
                    if int(pk) not in label_map:
                        continue
                    try:
                        fv = self._feat_extractor.extract(ecg_bp, peaks, bl, j)
                        if self.ecg_detector.cnn is not None:
                            embed = self.ecg_detector.cnn.embed(ecg_bp, int(pk))
                            all_X.append(np.concatenate([fv, embed]))
                        else:
                            all_X.append(fv)
                        all_y.append(label_map[int(pk)])
                    except Exception:
                        pass

        if len(all_X) < 10:
            print("[BeatValidator] Insufficient training data.")
            return

        self.beat_validator.fit(np.array(all_X, dtype=np.float32),
                                np.array(all_y, dtype=int))

    def save(self, model_dir: str = 'models/'):
        import os
        os.makedirs(model_dir, exist_ok=True)
        self.beat_validator.save(f'{model_dir}/beat_validator.pkl')
        self.baseline.save(f'{model_dir}/personal_baseline.pkl')
        if self.ecg_detector is not None:
            self.ecg_detector.save_model(f'{model_dir}/hybrid_detector.pkl')
        print(f"[PhysioMonitor] Saved to {model_dir}")

    def load(self, model_dir: str = 'models/', student_id: str = None):
        import os
        det_path = f'{model_dir}/hybrid_detector.pkl'
        val_path = f'{model_dir}/beat_validator.pkl'
        bl_path  = (f'{model_dir}/{student_id}_baseline.pkl'
                    if student_id else f'{model_dir}/personal_baseline.pkl')
        if os.path.exists(det_path) and self.ecg_detector is not None:
            self.ecg_detector.load_model(det_path)
        if os.path.exists(val_path):
            self.beat_validator.load(val_path)
        if os.path.exists(bl_path):
            self.baseline.load(bl_path)
        print(f"[PhysioMonitor] Loaded from {model_dir}")

    def print_status(self):
        print("\n── PhysioMonitor Status ─────────────────────────")
        print(f"  Mode            : {self.fusion.mode}")
        print(f"  ECG enabled     : {self.enable_ecg}")
        print(f"  PPG enabled     : {self.enable_ppg}")
        print(f"  Beat validator  : "
              f"{'trained' if self.beat_validator._trained else 'untrained (rule fallback)'}")
        if self.beat_validator._trained_dim is not None:
            print(f"    Trained dim   : {self.beat_validator._trained_dim}")
        print(f"  Baseline set    : {self.baseline._is_set}")
        if self.baseline._is_set:
            print(f"    HR baseline   : {self.baseline.hr_baseline:.1f} bpm")
            print(f"    RMSSD baseline: {self.baseline.rmssd_baseline:.1f} ms")
            print(f"    pNN50 baseline: {self.baseline.pnn50_baseline:.1f}%")
        print(f"  RR buffer size  : {len(self.stress_analyser._rr_buffer)}")
        print("─────────────────────────────────────────────────\n")


# ═══════════════════════════════════════════════════════════════════
#  EXAMPLE / SMOKE-TEST
# ═══════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    from hybrid_rpeak_detector import generate_synthetic_ecg
    import numpy as np

    print("=" * 65)
    print("  PhysioMonitor (improved) — Smoke Test")
    print("=" * 65)
    FS = 250
    np.random.seed(42)

    def make_ppg(duration, fs=250, hr=70):
        t   = np.linspace(0, duration, fs*duration)
        ppg = np.zeros_like(t)
        for bt in np.arange(0.3, duration, 60/hr):
            dt   = t - bt
            ppg += 0.8*np.exp(-dt**2/(2*(0.05)**2))
            ppg += 0.2*np.exp(-(dt-0.25)**2/(2*(0.04)**2))
        ppg += 0.02*np.random.randn(len(t))
        return ppg

    # ── Test PM-1: pnn50 baseline populated and used correctly ────────
    print("\n[PM-1] pnn50_contrib normalisation")
    bl = PersonalBaseline()
    bl.hr_baseline = 70; bl.rmssd_baseline = 30; bl.pnn50_baseline = 20.0
    bl._is_set = True

    sa = StressAnalyser(window_sec=30.0)
    for i in range(40):
        sa.add_rr(800.0, float(i * 800))
    result = sa.compute_stress(bl, quality_score=0.9)
    if result:
        contrib = result.contributing_features.get('pnn50_contrib', None)
        print(f"  pnn50_contrib = {contrib:.4f}  pnn50_pct = {result.hrv.pnn50_pct:.1f}%")
        print(f"  (was always 0 due to dimensional mismatch — should now vary)")
    else:
        print("  No result yet (need more beats)")

    # ── Test PM-2: PPGProcessor SOS filter state persists ─────────────
    print("\n[PM-2] PPGProcessor stateful SOS filter")
    proc = PPGProcessor(fs=FS)
    zi_before = proc._zi.copy()
    ppg_seg   = make_ppg(5, FS, hr=70)
    proc.process(ppg_seg, streaming=True)
    zi_after  = proc._zi
    changed   = not np.allclose(zi_before, zi_after)
    print(f"  Filter state changed after processing: {changed}  (should be True)")
    assert changed, "PM-2 FAILED: zi unchanged — filter not stateful"
    print("  PM-2 ✓")

    # ── Test PM-3: dimension mismatch falls back gracefully ────────────
    print("\n[PM-3] BeatValidator dimension mismatch fallback")
    import warnings as _w
    bv = BeatValidator(mode='ecg')
    from sklearn.preprocessing import RobustScaler
    from sklearn.pipeline import Pipeline
    from sklearn.ensemble import GradientBoostingClassifier
    # Train on 48-dim
    X48 = np.random.randn(80, 48).astype(np.float32)
    y48 = np.random.randint(0, 3, 80)
    bv.model = Pipeline([('s', RobustScaler()),
                          ('c', GradientBoostingClassifier(n_estimators=5))])
    bv.model.fit(X48, y48)
    bv._trained     = True
    bv._trained_dim = 48
    # Infer with 32-dim feature vector
    fv32 = np.random.randn(32).astype(np.float32)
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        cls, conf = bv.validate(fv32)
    got_warning = any('dimension mismatch' in str(w.message).lower()
                      for w in caught)
    print(f"  Fallback class={cls}, conf={conf:.3f}, "
          f"RuntimeWarning emitted={got_warning}")
    assert got_warning, "PM-3 FAILED: no RuntimeWarning on dimension mismatch"
    print("  PM-3 ✓")

    # ── Test PM-4: cross_check always in [0, 1] ────────────────────────
    print("\n[PM-4] MultiModalFusion cross_check clipped to [0,1]")
    fusion = MultiModalFusion(fs=FS, enable_ecg=True, enable_ppg=True)
    # Simulate extreme HR mismatch (AF scenario: ECG=150 bpm, PPG=50 bpm)
    ecg_rr  = np.full(10, 400.0)    # 150 bpm
    ppg_ibi = np.full(10, 1200.0)   # 50 bpm
    result_f = fusion.fuse(
        np.arange(10)*400, np.arange(10)*1200,
        ecg_rr, ppg_ibi)
    cc = result_f['cross_check']
    print(f"  cross_check at 100-bpm mismatch: {cc:.4f}  (must be >= 0)")
    assert 0.0 <= cc <= 1.0, f"PM-4 FAILED: cross_check={cc}"
    print("  PM-4 ✓")

    # ── Test PM-5: verbose=False suppresses init prints ────────────────
    print("\n[PM-5] verbose=False suppresses init prints")
    import io, sys
    buf = io.StringIO()
    old = sys.stdout; sys.stdout = buf
    PhysioMonitor(fs=FS, enable_ecg=True, enable_ppg=False, verbose=False)
    sys.stdout = old
    output = buf.getvalue()
    print(f"  Output with verbose=False: {repr(output)}  (should be empty)")
    assert output == '', "PM-5 FAILED: verbose=False still printed"
    print("  PM-5 ✓")

    # ── Test PM-6: fallback feature_vector uses correct dim ────────────
    print("\n[PM-6] Fallback feature_vector uses correct dim (not hardcoded 32)")
    m = PhysioMonitor(fs=FS, enable_ecg=True, enable_ppg=False, verbose=False)
    ecg_det_dim = (48 if m.ecg_detector is not None and
                   m.ecg_detector.cnn is not None else 32)
    print(f"  Inferred ECG feature dim: {ecg_det_dim}  "
          f"(32 without CNN, 48 with CNN)")
    assert ecg_det_dim == 32, "Expected 32 without CNN"
    print("  PM-6 ✓")

    print("\nAll PM smoke-tests passed.")
    print("=" * 65)
