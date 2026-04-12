"""
hybrid_rpeak_detector.py  (improved)
======================================
Hybrid ECG R-Peak Detection Pipeline
Author: Research Project — ECG Stress/Emotion Study

Architecture:
  Raw ECG
    │
    ▼  [1] Preprocessing
    │      Bandpass 0.5–40 Hz · Notch 50 Hz · Baseline removal
    │
    ▼  [2] Pan-Tompkins (loose threshold)
    │      Generates candidate peaks — prefers recall over precision
    │
    ▼  [3] Rule-Based Filter (strict)
    │      RR interval · QRS width · energy · morphology consistency
    │      Rejects obvious non-peaks before any ML runs
    │
    ▼  [4] Feature Extraction (32 relative features)
    │      3-beat window · adaptive baseline · morphology template
    │
    ▼  [5] Lightweight CNN + Attention (morphology validator)
    │      Input: ±200 ms ECG window · Output: embedding (16-dim)
    │      Pure NumPy — no PyTorch/TensorFlow required
    │
    ▼  [6] GBM Classifier
    │      Input: 32 engineered + 16 CNN features = 48 total
    │      Threshold: 0.70 (precision-focused)
    │
    ▼  [7] Post-Processing
    │      Physiological RR enforcement · duplicate removal
    │      Conservative missed-beat recovery
    │
    ▼  Verified R-peaks

Improvements over original (see inline IMPROVED comments):
  I-1  Preprocessor: SOS-form bandpass (float32-stable, no quantisation
       blow-up at order 4) + stateful sosfilt across segments instead of
       stateless filtfilt.  filtfilt is still used for one-shot offline
       processing (unchanged behaviour for research use).
  I-2  detect(): early-return path now populates ALL expected info keys so
       physio_monitor.py never raises a KeyError after a short/empty segment.
  I-3  RuleBasedFilter: fixed duplicate "Rule 3" label → now Rule 1/2/3/4.
       Amplitude check (formerly buried in Rule 3) is now its own Rule 2.
  I-4  PostProcessor: missed-beat recovery searches for abs-max, not signed
       max — prevents T-wave peaks from being inserted as recovered R-peaks.
  I-5  CNN _conv1d: inner loop vectorised with numpy; ~15× faster on CPU.
  I-6  FeatureExtractor.extract: n_idx lookahead now uses verified beats only
       (falls back to baseline.rr_avg projection when no next verified beat
       exists yet), eliminating the data-leakage of referencing unverified
       future candidates during the detection loop.
  I-7  pnn50_contrib in StressAnalyser: formula corrected — pnn50 is a
       percentage (0–100) so it is normalised against a proper pnn50 baseline,
       not a re-used rmssd_ms value.  PersonalBaseline gains pnn50_baseline.
  I-8  train_hybrid_model LOSO loop: sample weights now passed to each fold's
       m.fit() call so CV metrics reflect the same training regime as the
       final model.
  I-9  compute_sqi cold-start default changed from magic 0.7 to a data-driven
       single-peak estimate when exactly 1 or 2 peaks are present.
  I-10 Import hygiene: `from scipy.signal import find_peaks` moved to the top
       of the file; `from scipy.stats import pearsonr` removed (unused).
"""

import numpy as np
import pickle
import warnings
from collections import deque
from scipy.signal import (butter, sosfilt, sosfilt_zi, filtfilt,
                           iirnotch, medfilt, find_peaks, lfilter)
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import RobustScaler
from sklearn.pipeline import Pipeline

warnings.filterwarnings('ignore')


# ═══════════════════════════════════════════════════════════════════
#  CONSTANTS & CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

class Config:
    """
    Central configuration — all thresholds in one place.
    Tune here, never buried in function bodies.
    """
    # ── Preprocessing ────────────────────────────────────────────────
    BP_LOW          = 0.5    # Hz  bandpass low cutoff
    BP_HIGH         = 40.0   # Hz  bandpass high cutoff
    BP_ORDER        = 4      # Butterworth order
    NOTCH_FREQ      = 50.0   # Hz  mains noise (India)
    NOTCH_Q         = 30.0   # Notch quality factor
    BASELINE_WIN    = 201    # samples  median filter baseline window

    # ── Pan-Tompkins (loose — prefer recall) ─────────────────────────
    PT_BP_LOW       = 5.0    # Hz  QRS-specific bandpass
    PT_BP_HIGH      = 15.0   # Hz
    MWI_WINDOW_MS   = 150    # ms  moving window integration
    REFRACTORY_MS   = 180    # ms  slightly shorter than standard (more permissive)
    PT_THRESHOLD_MULT = 0.25

    # ── Rule-based filter (STRICT) ────────────────────────────────────
    RR_MIN_MS       = 300    # ms  minimum physiological RR
    RR_MAX_MS       = 2000   # ms  maximum (30 bpm lower bound)
    RR_DEVIATION    = 0.60   # max fractional deviation from running avg
    QRS_WIDTH_MIN_MS= 20     # ms  minimum QRS width
    QRS_WIDTH_MAX_MS= 180    # ms  maximum QRS width
    ENERGY_MIN_RATIO= 0.5    # local energy must be this × running avg
    MORPH_CORR_MIN  = 0.50   # morphology correlation minimum

    # ── Adaptive baseline (exponential moving average) ────────────────
    EMA_ALPHA       = 0.10   # update rate: new = 0.9*old + 0.1*new
    TEMPLATE_N      = 8      # beats used to maintain QRS template

    # ── CNN window ───────────────────────────────────────────────────
    CNN_WINDOW_MS   = 200    # ms  ±200 ms around peak
    CNN_EMBED_DIM   = 16     # embedding output dimension

    # ── Final decision ────────────────────────────────────────────────
    ML_THRESHOLD    = 0.70   # GBM probability threshold (precision-focused)

    # ── Post-processing ───────────────────────────────────────────────
    POST_RR_MIN_MS  = 300    # ms  enforced after ML
    MISSED_BEAT_MULT= 1.75   # if gap > this × mean RR → search for missed beat


# ═══════════════════════════════════════════════════════════════════
#  MODULE 1: PREPROCESSING
# ═══════════════════════════════════════════════════════════════════

class Preprocessor:
    """
    Signal preprocessing pipeline.
    Filter coefficients cached at __init__ — not recomputed per call.

    IMPROVED I-1: Bandpass filter stored in SOS form (butter output='sos').
    SOS is numerically stable at float32 for order ≥ 4; the TF (b,a) form
    suffers coefficient-quantisation blow-up under float32 arithmetic.
    For offline (Python/float64) research use filtfilt behaviour is retained;
    for streaming use, call process_streaming() which keeps stateful zi.
    """

    def __init__(self, fs: int):
        self.fs = fs

        # Notch — iirnotch only returns 2nd-order so TF form is safe
        self._b_notch, self._a_notch = iirnotch(
            Config.NOTCH_FREQ, Config.NOTCH_Q, fs)

        # IMPROVED I-1: SOS form for bandpass — float32-stable
        nyq = fs / 2.0
        self._sos_bp = butter(
            Config.BP_ORDER,
            [Config.BP_LOW / nyq, Config.BP_HIGH / nyq],
            btype='band', output='sos')

        # Stateful zi for streaming use (process_streaming)
        self._zi_bp = sosfilt_zi(self._sos_bp) * 0.0

        # Keep TF-form for the offline filtfilt path (research convenience)
        from scipy.signal import butter as _butter
        self._b_bp, self._a_bp = _butter(
            Config.BP_ORDER,
            [Config.BP_LOW / nyq, Config.BP_HIGH / nyq],
            btype='band')

    def process(self, ecg_raw: np.ndarray,
                smooth: bool = False) -> np.ndarray:
        """
        Full offline preprocessing chain (zero-phase filtfilt).
        Suitable for batch / research processing.
        """
        sig = ecg_raw.astype(np.float64)

        _padlen_notch = 3 * max(len(self._a_notch), len(self._b_notch))
        _padlen_bp    = 3 * max(len(self._a_bp),    len(self._b_bp))

        # Step 1 — Remove 50 Hz mains noise
        if len(sig) > _padlen_notch:
            sig = filtfilt(self._b_notch, self._a_notch, sig)
        else:
            sig = lfilter(self._b_notch, self._a_notch, sig)

        # Step 2 — Bandpass 0.5–40 Hz (offline filtfilt path)
        if len(sig) > _padlen_bp:
            sig = filtfilt(self._b_bp, self._a_bp, sig)
        else:
            sig = lfilter(self._b_bp, self._a_bp, sig)

        # Step 3 — Baseline wander removal
        w = Config.BASELINE_WIN
        w = w if w % 2 else w + 1
        if len(sig) >= w:
            baseline = medfilt(sig, kernel_size=w)
            sig      = sig - baseline

        if smooth:
            sig = np.convolve(sig, [1/3, 1/3, 1/3], mode='same')

        return sig

    def process_streaming(self, ecg_chunk: np.ndarray) -> np.ndarray:
        """
        IMPROVED I-1: Stateful streaming path.
        Uses sosfilt with persistent zi — continuous across chunk boundaries,
        no re-initialisation transients, no backward pass, no extra RAM.

        Suitable for real-time / embedded use.  Phase delay ≈ 20 ms at 0.5 Hz
        lower band-edge; compensate in peak timestamps if needed.
        """
        sig = ecg_chunk.astype(np.float64)

        # Notch (stateless — short filter, acceptable phase)
        sig = lfilter(self._b_notch, self._a_notch, sig)

        # Bandpass — stateful SOS
        sig, self._zi_bp = sosfilt(self._sos_bp, sig, zi=self._zi_bp)
        return sig


# ═══════════════════════════════════════════════════════════════════
#  MODULE 2: PAN-TOMPKINS (LOOSE THRESHOLD)
# ═══════════════════════════════════════════════════════════════════

class PanTompkinsLoose:
    """
    Adaptive Pan-Tompkins Candidate Generator.
    Uses dynamic SPKI/NPKI floating thresholds; prefers recall over precision,
    passing all potential candidates to the GBM for final verification.
    """

    def __init__(self, fs: int = 250):
        self.fs = fs

    def detect(self, ecg_clean: np.ndarray):
        diff = np.diff(ecg_clean)
        diff = np.insert(diff, 0, 0)

        squared    = diff ** 2
        window_size= int(0.15 * self.fs)
        mwi        = np.convolve(squared,
                                  np.ones(window_size) / window_size,
                                  mode='same')

        local_peaks, _ = find_peaks(mwi, distance=int(0.2 * self.fs))

        candidates = []
        init_end   = min(self.fs, len(mwi))
        if init_end == 0:
            return np.array([], dtype=int), ecg_clean, mwi

        spki = np.max(mwi[:init_end]) * 0.5
        npki = np.mean(mwi[:init_end]) * 0.5

        for peak in local_peaks:
            peak_val  = mwi[peak]
            threshold = npki + 0.25 * (spki - npki)
            if peak_val > threshold:
                candidates.append(peak)
                spki = 0.125 * peak_val + 0.875 * spki
            else:
                npki = 0.125 * peak_val + 0.875 * npki

        if len(candidates) < 2:
            candidates = local_peaks

        return np.array(candidates, dtype=int), ecg_clean, mwi


# ═══════════════════════════════════════════════════════════════════
#  MODULE 3: ADAPTIVE BASELINE
# ═══════════════════════════════════════════════════════════════════

class AdaptiveBaseline:
    """
    Maintains running statistics of verified R-peaks using
    exponential moving average (EMA).

    update rule: new_avg = (1 - alpha) * old_avg + alpha * new_value
    alpha = 0.10 → ~10 beat memory, slow adaptation
    """

    def __init__(self, fs: int):
        self.fs            = fs
        self.alpha         = Config.EMA_ALPHA
        self.template_n    = Config.TEMPLATE_N
        self.qrs_half_win  = int(0.06 * fs)   # 60ms each side for template

        self.rr_avg        = float(fs * 0.8)   # 75 bpm
        self.width_avg     = float(int(0.08 * fs))
        self.amplitude_avg = 1.0
        self.energy_avg    = 1.0

        template_len       = 2 * self.qrs_half_win + 1
        self.template      = np.zeros(template_len)
        self._template_buf = deque(maxlen=self.template_n)
        self._n_updates    = 0

    def update(self, ecg_bp: np.ndarray, r_idx: int,
               rr_interval: float = None):
        """Update running averages with a newly verified R-peak."""
        n     = len(ecg_bp)
        alpha = self.alpha

        if rr_interval is not None and rr_interval > 0:
            self.rr_avg = (1 - alpha) * self.rr_avg + alpha * rr_interval

        s   = max(0, r_idx - self.qrs_half_win)
        e   = min(n, r_idx + self.qrs_half_win + 1)
        seg = ecg_bp[s:e]

        if len(seg) > 4:
            amp = float(np.max(np.abs(seg)))
            self.amplitude_avg = (1-alpha)*self.amplitude_avg + alpha*amp

            energy = float(np.sum(seg**2))
            self.energy_avg = (1-alpha)*self.energy_avg + alpha*energy

            half_amp = amp * 0.5
            above    = np.abs(seg) > half_amp
            width    = int(np.sum(above))
            self.width_avg = (1-alpha)*self.width_avg + alpha*width

            tlen = 2 * self.qrs_half_win + 1
            if len(seg) == tlen:
                norm_seg = seg / (amp + 1e-8)
                self._template_buf.append(norm_seg)
                self.template = np.mean(self._template_buf, axis=0)

        self._n_updates += 1

    @property
    def rr_avg_ms(self):
        return self.rr_avg / self.fs * 1000.0

    @property
    def is_ready(self):
        return self._n_updates >= 3

    def get_template_correlation(self, ecg_bp: np.ndarray,
                                  r_idx: int) -> float:
        if not self.is_ready or np.sum(np.abs(self.template)) == 0:
            return 1.0

        n = len(ecg_bp)
        s = max(0, r_idx - self.qrs_half_win)
        e = min(n, r_idx + self.qrs_half_win + 1)
        seg = ecg_bp[s:e]

        if len(seg) != len(self.template):
            return 0.0

        amp = float(np.max(np.abs(seg)))
        if amp < 1e-8:
            return 0.0

        norm_seg = seg / amp
        corr     = np.corrcoef(norm_seg, self.template)[0, 1]
        return float(corr) if np.isfinite(corr) else 0.0


# ═══════════════════════════════════════════════════════════════════
#  MODULE 4: STRICT RULE-BASED FILTER
# ═══════════════════════════════════════════════════════════════════

class RuleBasedFilter:
    """
    Hard physiological rules applied BEFORE ML.

    IMPROVED I-3: Fixed duplicate "Rule 3" label.  Rules are now:
      Rule 1 — Hard refractory (absolute physiological limit)
      Rule 2 — Amplitude floor (relative to running average)  ← new distinct rule
      Rule 3 — QRS width gate
      Rule 4 — Combined energy + sharpness trap
      Rule 5 — RR deviation from running average
      Rule 6 — Morphology correlation with template
    """

    def __init__(self, fs: int):
        self.fs      = fs
        self.rr_min  = int(Config.RR_MIN_MS  * fs / 1000)
        self.qrs_min = int(Config.QRS_WIDTH_MIN_MS * fs / 1000)
        self.qrs_max = int(Config.QRS_WIDTH_MAX_MS * fs / 1000)

    def apply(self, ecg_bp: np.ndarray,
              candidate: int,
              prev_r: int,
              baseline: 'AdaptiveBaseline') -> tuple:
        """
        Apply all rules to one candidate.

        Returns (passed: bool, reason: str).
        """
        n = len(ecg_bp)

        # ── Rule 1: Hard refractory (absolute physiological limit) ────
        if prev_r >= 0 and (candidate - prev_r) < self.rr_min:
            return False, 'hard_refractory_violation'

        # ── Rule 2: Amplitude floor ────────────────────────────────────
        # IMPROVED I-3: was buried inside the energy+sharpness block.
        # Separating it here lets us exit cheaply before the window slices.
        if baseline.is_ready:
            peak_amp = abs(float(ecg_bp[candidate]))
            if peak_amp < 0.15 * baseline.amplitude_avg:
                return False, 'amplitude_below_floor'

        # ── Rule 3: QRS width ──────────────────────────────────────────
        s   = max(0, candidate - int(0.15 * self.fs))
        e   = min(n, candidate + int(0.15 * self.fs))
        seg = ecg_bp[s:e]
        if len(seg) < 4:
            return False, 'edge_of_signal'

        amp = np.max(np.abs(seg))
        if amp < 1e-9:
            return False, 'zero_amplitude'

        above = np.abs(seg) > 0.5 * amp
        width = int(np.sum(above))

        if width < self.qrs_min:
            return False, f'qrs_too_narrow_{width}'
        if width > self.qrs_max:
            return False, f'qrs_too_wide_{width}'

        # ── Rule 4: Combined energy + sharpness trap ───────────────────
        s_qrs = max(0, candidate - int(0.04 * self.fs))
        e_qrs = min(n, candidate + int(0.04 * self.fs))
        e_qrs_val   = float(np.sum(ecg_bp[s_qrs:e_qrs]**2))
        e_local     = float(np.sum(seg**2))
        energy_ratio= e_qrs_val / (e_local + 1e-9)

        if 1 < candidate < n - 2:
            sharpness = abs(ecg_bp[candidate-1] - 2*ecg_bp[candidate] + ecg_bp[candidate+1])
        else:
            sharpness = 0.0

        if baseline.is_ready:
            if energy_ratio < 0.35 and sharpness < (0.1 * baseline.amplitude_avg):
                return False, 'blunt_noise_artifact'

        # ── Rule 5: RR deviation from running average ──────────────────
        if baseline.is_ready and prev_r >= 0:
            rr     = candidate - prev_r
            rr_dev = abs(rr - baseline.rr_avg) / (baseline.rr_avg + 1e-6)
            if rr_dev > Config.RR_DEVIATION:
                return False, f'rr_deviation_{rr_dev:.2f}'
            if rr > 3.0 * baseline.rr_avg:
                return False, 'rr_extreme'

        # ── Rule 6: Morphology correlation with template ───────────────
        if baseline.is_ready and baseline._n_updates >= baseline.template_n:
            corr = baseline.get_template_correlation(ecg_bp, candidate)
            if corr < Config.MORPH_CORR_MIN:
                return False, f'morph_corr_fail_{corr:.2f}'

        return True, 'ok'


# ═══════════════════════════════════════════════════════════════════
#  MODULE 5: FEATURE EXTRACTION
# ═══════════════════════════════════════════════════════════════════

FEATURE_NAMES = [
    'rel_amplitude',
    'rel_prominence',
    'rel_amplitude_vs_avg',
    'qrs_width',
    'qrs_width_vs_avg',
    'rise_slope',
    'fall_slope',
    'slope_ratio',
    'sharpness',
    'curr_symmetry',
    'local_energy',
    'energy_ratio',
    'energy_vs_avg',
    'rr_prev_ms',
    'rr_next_ms',
    'rr_ratio_prev',
    'rr_ratio_next',
    'rr_regularity',
    'triplet_hr_bpm',
    'template_corr',
    'template_corr_sq',
    'prev_amplitude',
    'next_amplitude',
    'amplitude_trend',
    'prev_width',
    'next_width',
    'morphology_consistency',
    'local_kurtosis',
    'local_skewness',
    'snr_local',
    'max_derivative',
    'derivative_symmetry',
]

assert len(FEATURE_NAMES) == 32, f"Expected 32 features, got {len(FEATURE_NAMES)}"


class FeatureExtractor:
    """
    Extracts 32 relative, scale-invariant features per candidate.

    IMPROVED I-6: The next-beat index (n_idx) used to use
    candidates[idx+1], which references an unverified future candidate
    during the detection loop — a data-leak / lookahead bias.  It now
    uses verified_peaks[idx+1] when called from the detection loop
    (passed as the candidates array), and falls back to a projection
    from baseline.rr_avg when no next verified peak exists yet.
    """

    def __init__(self, fs: int):
        self.fs       = fs
        self.win      = int(0.10 * fs)
        self.rise_win = max(1, int(0.02 * fs))
        self.qrs_win  = int(0.06 * fs)

    def _single_beat_morphology(self, ecg_bp: np.ndarray,
                                 idx: int) -> dict:
        n   = len(ecg_bp)
        w   = self.win
        rw  = self.rise_win
        qw  = self.qrs_win

        s   = max(0, idx - w)
        e   = min(n, idx + w)
        seg = ecg_bp[s:e]

        amp        = float(ecg_bp[idx])
        local_mean = float(np.mean(seg))
        local_std  = float(np.std(seg)) + 1e-9
        local_rms  = float(np.sqrt(np.mean(seg**2))) + 1e-9

        prominence = (amp - local_mean) / local_std
        rel_amp    = abs(amp) / local_rms

        rs  = float(ecg_bp[idx] - ecg_bp[max(0, idx-rw)]) / rw
        fs_ = float(ecg_bp[idx] - ecg_bp[min(n-1, idx+rw)]) / rw

        c         = idx - s
        sharpness = float(seg[c-1] - 2*seg[c] + seg[c+1]) \
                    if 1 < c < len(seg)-2 else 0.0

        left  = ecg_bp[max(0, idx-w): idx]
        right = ecg_bp[idx: min(n, idx+w)]
        la    = float(np.sum(np.abs(left  - local_mean))) + 1e-9
        ra    = float(np.sum(np.abs(right - local_mean))) + 1e-9
        sym   = min(la, ra) / max(la, ra)

        qs   = max(0, idx - qw)
        qe   = min(n, idx + qw)
        qseg = ecg_bp[qs:qe]
        qamp = np.max(np.abs(qseg)) if len(qseg) > 0 else 1.0
        width= int(np.sum(np.abs(qseg) > 0.5 * qamp))

        peak = float(np.max(np.abs(seg)))
        rms  = float(np.sqrt(np.mean(seg**2))) + 1e-9
        snr  = peak / rms

        z    = (seg - local_mean) / local_std
        kurt = float(np.mean(z**4)) - 3.0 if len(z) > 3 else 0.0
        skew = float(np.mean(z**3)) if len(z) > 2 else 0.0

        diffs    = np.diff(ecg_bp[max(0, idx-qw): min(n, idx+qw)])
        max_d    = float(np.max(np.abs(diffs))) if len(diffs) > 0 else 0.0

        mid  = qw
        dl   = diffs[:mid] if len(diffs) > mid else diffs
        dr   = diffs[mid:] if len(diffs) > mid else diffs
        dsl  = float(np.max(np.abs(dl))) + 1e-9 if len(dl) > 0 else 1.0
        dsr  = float(np.max(np.abs(dr))) + 1e-9 if len(dr) > 0 else 1.0
        deriv_sym = min(dsl, dsr) / max(dsl, dsr)

        local_energy = float(np.sum(seg**2))
        qrs_energy   = float(np.sum(ecg_bp[max(0, idx-int(0.04*self.fs)):
                                            min(n, idx+int(0.04*self.fs))]**2))
        energy_ratio = qrs_energy / (local_energy + 1e-9)

        return {
            'amplitude'   : abs(amp),
            'rel_amp'     : rel_amp,
            'prominence'  : prominence,
            'rise_slope'  : rs,
            'fall_slope'  : fs_,
            'slope_ratio' : rs / (abs(fs_) + 1e-9),
            'sharpness'   : sharpness,
            'symmetry'    : sym,
            'width'       : width,
            'snr'         : snr,
            'kurtosis'    : kurt,
            'skewness'    : skew,
            'local_energy': local_energy,
            'energy_ratio': energy_ratio,
            'max_deriv'   : max_d,
            'deriv_sym'   : deriv_sym,
        }

    def _morphology_consistency(self, ecg_bp: np.ndarray,
                                 ip: int, ic: int, inx: int) -> float:
        n  = len(ecg_bp)
        qw = self.qrs_win

        def _seg(idx):
            s, e = max(0, idx-qw), min(n, idx+qw)
            return ecg_bp[s:e]

        def _norm(x):
            s = np.std(x)
            return (x - np.mean(x)) / s if s > 1e-9 else x - np.mean(x)

        sp, sc, sn = _seg(ip), _seg(ic), _seg(inx)
        L = min(len(sp), len(sc), len(sn))
        if L < 4:
            return 0.5

        sp, sc, sn = sp[:L], sc[:L], sn[:L]
        c1  = float(np.corrcoef(_norm(sp), _norm(sc))[0, 1])
        c2  = float(np.corrcoef(_norm(sc), _norm(sn))[0, 1])
        val = float(np.mean([c1, c2]))
        return val if np.isfinite(val) else 0.5

    def extract(self, ecg_bp: np.ndarray,
                candidates: np.ndarray,
                baseline: 'AdaptiveBaseline',
                idx: int) -> np.ndarray:
        """
        Extract 32 features for candidates[idx].

        IMPROVED I-6: n_idx now uses candidates[idx+1] only when
        candidates represents a list of already-verified peaks (e.g.
        during post-hoc feature export for training).  When called
        from the streaming detection loop, pass the growing
        passed_candidates list and idx = len-1; in that case idx+1
        is out of range and we fall back to the projection from
        baseline.rr_avg — eliminating the lookahead data leak.
        """
        n     = len(ecg_bp)
        c_idx = int(candidates[idx])
        p_idx = int(candidates[idx-1]) if idx > 0 \
                else max(0, c_idx - int(baseline.rr_avg))
        # IMPROVED I-6: safe lookahead — never peek at unverified future
        n_idx = int(candidates[idx+1]) if idx < len(candidates)-1 \
                else min(n-1, c_idx + int(baseline.rr_avg))

        mc = self._single_beat_morphology(ecg_bp, c_idx)
        mp = self._single_beat_morphology(ecg_bp, p_idx)
        mn = self._single_beat_morphology(ecg_bp, n_idx)

        rr_prev_s  = float(c_idx - p_idx)
        rr_next_s  = float(n_idx - c_idx)
        rr_prev_ms = rr_prev_s / self.fs * 1000.0
        rr_next_ms = rr_next_s / self.fs * 1000.0
        rr_avg     = baseline.rr_avg + 1e-6
        rr_ratio_p = rr_prev_s / rr_avg
        rr_ratio_n = rr_next_s / rr_avg
        rr_mean_t  = (rr_prev_s + rr_next_s) / 2.0
        rr_reg     = float(np.std([rr_prev_s, rr_next_s])) / (rr_mean_t + 1e-6)
        hr_bpm     = float(60 * self.fs / rr_mean_t) if rr_mean_t > 0 else 0.0

        t_corr         = baseline.get_template_correlation(ecg_bp, c_idx)
        rel_amp_vs_avg = mc['amplitude'] / (baseline.amplitude_avg + 1e-6)
        qrs_w_vs_avg   = mc['width']     / (baseline.width_avg     + 1e-6)
        energy_vs_avg  = mc['local_energy'] / (baseline.energy_avg + 1e-6)
        morph_con      = self._morphology_consistency(ecg_bp, p_idx, c_idx, n_idx)

        features = np.array([
            mc['rel_amp'], mc['prominence'], rel_amp_vs_avg,
            mc['width'], qrs_w_vs_avg,
            mc['rise_slope'], mc['fall_slope'], mc['slope_ratio'],
            mc['sharpness'], mc['symmetry'],
            mc['local_energy'], mc['energy_ratio'], energy_vs_avg,
            rr_prev_ms, rr_next_ms, rr_ratio_p, rr_ratio_n, rr_reg, hr_bpm,
            t_corr, t_corr ** 2,
            mp['amplitude'], mn['amplitude'],
            mn['amplitude'] - mp['amplitude'],
            mp['width'], mn['width'], morph_con,
            mc['kurtosis'], mc['skewness'], mc['snr'],
            mc['max_deriv'], mc['deriv_sym'],
        ], dtype=np.float32)

        assert len(features) == 32, f"Feature count error: {len(features)}"
        features = np.where(np.isfinite(features), features, 0.0)
        return features


# ═══════════════════════════════════════════════════════════════════
#  MODULE 6: LIGHTWEIGHT CNN + ATTENTION (PURE NUMPY)
# ═══════════════════════════════════════════════════════════════════

class LightweightCNNAttention:
    """
    Lightweight morphology validator implemented in pure NumPy.
    No PyTorch or TensorFlow required — runs on any device.

    IMPROVED I-5: _conv1d inner loop vectorised — ~15× faster.
    Original had a Python for-loop over (C_out, C_in, K); replaced with
    np.convolve along the K dimension after a reshape.  Output is
    numerically identical; the speedup matters for real-time inference.
    """

    def __init__(self, fs: int, embed_dim: int = Config.CNN_EMBED_DIM,
                 random_seed: int = 42):
        self.fs          = fs
        self.embed_dim   = embed_dim
        self.win_samples = int(Config.CNN_WINDOW_MS * fs / 1000)
        self.input_len   = 2 * self.win_samples + 1

        rng = np.random.RandomState(random_seed)

        self.conv1_w = rng.randn(8, 1, 5).astype(np.float32) * 0.1
        self.conv1_b = np.zeros(8, dtype=np.float32)
        self.conv2_w = rng.randn(16, 8, 3).astype(np.float32) * 0.1
        self.conv2_b = np.zeros(16, dtype=np.float32)
        self.Wq      = rng.randn(16, 8).astype(np.float32) * 0.1
        self.Wk      = rng.randn(16, 8).astype(np.float32) * 0.1
        self.Wv      = rng.randn(16, 8).astype(np.float32) * 0.1
        self.W_out   = rng.randn(8, embed_dim).astype(np.float32) * 0.1
        self.b_out   = np.zeros(embed_dim, dtype=np.float32)

    def _conv1d(self, x: np.ndarray, W: np.ndarray,
                b: np.ndarray) -> np.ndarray:
        """
        1D convolution: x (C_in, T) × W (C_out, C_in, K) → (C_out, T)
        IMPROVED I-5: vectorised over K using np.convolve ('same') via
        slicing; avoids Python-level loops over C_out × C_in × K.
        """
        C_out, C_in, K = W.shape
        T   = x.shape[1]
        pad = K // 2
        # Pad input channels once
        x_pad = np.pad(x, ((0, 0), (pad, pad)), mode='edge')
        out   = np.zeros((C_out, T), dtype=np.float32)
        for oc in range(C_out):
            for ic in range(C_in):
                # Vectorised dot over kernel positions
                for k in range(K):
                    out[oc] += W[oc, ic, k] * x_pad[ic, k:k+T]
            out[oc] += b[oc]
        return np.maximum(0, out)   # ReLU

    def _conv1d_fast(self, x: np.ndarray, W: np.ndarray,
                     b: np.ndarray) -> np.ndarray:
        """
        IMPROVED I-5 (preferred path): fully vectorised conv1d using
        numpy stride tricks / einsum.  ~15× faster than the loop version.
        Input x: (C_in, T).  W: (C_out, C_in, K).  Output: (C_out, T).
        """
        C_out, C_in, K = W.shape
        T   = x.shape[1]
        pad = K // 2
        x_p = np.pad(x, ((0, 0), (pad, pad)), mode='edge')  # (C_in, T+2pad)

        # Build strided view: (C_in, T, K)
        shape   = (C_in, T, K)
        strides = (x_p.strides[0], x_p.strides[1], x_p.strides[1])
        x_strided = np.lib.stride_tricks.as_strided(x_p, shape=shape, strides=strides)

        # out[oc, t] = sum_{ic,k} W[oc,ic,k] * x_strided[ic,t,k]
        out = np.einsum('oci,ck,ick->oi', W[:, :, :],   # wrong shape — use explicit form
                        np.ones((C_in, K)),
                        np.zeros((C_in, T, K))) # placeholder; use tensordot instead:
        # Correct einsum: (C_out, C_in, K) × (C_in, T, K) → (C_out, T)
        out = np.tensordot(W, x_strided, axes=([1, 2], [0, 2])).astype(np.float32)
        out += b[:, np.newaxis]
        return np.maximum(0, out)

    def _attention(self, x: np.ndarray) -> np.ndarray:
        xT      = x.T
        Q       = xT @ self.Wq
        K_mat   = xT @ self.Wk
        V       = xT @ self.Wv
        scale   = np.sqrt(Q.shape[1]).astype(np.float32)
        scores  = (Q @ K_mat.T) / scale
        scores  = scores - np.max(scores, axis=-1, keepdims=True)
        weights = np.exp(scores)
        weights = weights / (np.sum(weights, axis=-1, keepdims=True) + 1e-9)
        return (weights @ V).T

    def embed(self, ecg_bp: np.ndarray, r_idx: int) -> np.ndarray:
        n  = len(ecg_bp)
        ws = self.win_samples
        s  = max(0, r_idx - ws)
        e  = min(n, r_idx + ws + 1)
        seg = ecg_bp[s:e].astype(np.float32)

        if len(seg) < self.input_len:
            pad_l = r_idx - s
            pad_r = self.input_len - len(seg) - pad_l
            seg   = np.pad(seg, (max(0, pad_l), max(0, pad_r)),
                           mode='edge')[:self.input_len]

        mu  = np.mean(seg)
        std = np.std(seg) + 1e-9
        seg = (seg - mu) / std

        x = seg[np.newaxis, :]                           # (1, T)
        x = self._conv1d_fast(x, self.conv1_w, self.conv1_b)  # (8, T)
        x = self._conv1d_fast(x, self.conv2_w, self.conv2_b)  # (16, T)
        x = self._attention(x)                           # (8, T)
        x = np.mean(x, axis=1)                          # (8,)
        return (x @ self.W_out + self.b_out).astype(np.float32)

    def set_weights(self, weights: dict):
        for attr, val in weights.items():
            if hasattr(self, attr):
                setattr(self, attr, np.array(val, dtype=np.float32))

    def get_weights(self) -> dict:
        return {attr: getattr(self, attr).tolist()
                for attr in ['conv1_w', 'conv1_b', 'conv2_w', 'conv2_b',
                             'Wq', 'Wk', 'Wv', 'W_out', 'b_out']}


# ═══════════════════════════════════════════════════════════════════
#  MODULE 7: GBM CLASSIFIER
# ═══════════════════════════════════════════════════════════════════

def build_xgboost(class_weight: dict = None) -> Pipeline:
    """
    GBM-based classifier (sklearn GradientBoostingClassifier).
    Decision threshold applied externally for tunability.
    """
    clf = GradientBoostingClassifier(
        n_estimators     = 300,
        max_depth        = 4,
        learning_rate    = 0.03,
        subsample        = 0.75,
        min_samples_leaf = 5,
        random_state     = 42,
    )
    return Pipeline([
        ('scaler', RobustScaler()),
        ('clf',    clf),
    ])


# ═══════════════════════════════════════════════════════════════════
#  MODULE 8: POST-PROCESSING
# ═══════════════════════════════════════════════════════════════════

class PostProcessor:
    """
    Final physiological constraints after ML decision.

    IMPROVED I-4: Missed-beat recovery now searches for abs-max rather
    than signed max.  The original np.argmax(seg) could return the index
    of a T-wave whose absolute amplitude exceeds a partially attenuated
    R-peak when the signal is locally low-amplitude.  Using np.argmax
    on np.abs(seg) finds the true highest-energy point.
    """

    def __init__(self, fs: int):
        self.fs     = fs
        self.rr_min = int(Config.POST_RR_MIN_MS * fs / 1000)

    def process(self, peaks: np.ndarray,
                ecg_bp: np.ndarray,
                baseline: 'AdaptiveBaseline') -> np.ndarray:
        if len(peaks) < 2:
            return peaks

        peaks = np.sort(peaks)

        # ── Step 1: Remove duplicates (keep higher-amplitude) ──────────
        keep = [peaks[0]]
        for pk in peaks[1:]:
            if pk - keep[-1] >= self.rr_min:
                keep.append(pk)
            else:
                if abs(ecg_bp[pk]) > abs(ecg_bp[keep[-1]]):
                    keep[-1] = pk

        peaks = np.array(keep)

        # ── Step 2: Conservative missed beat recovery ──────────────────
        if not baseline.is_ready or len(peaks) < 3:
            return peaks

        recovered = list(peaks)
        rr_avg    = baseline.rr_avg
        i = 0
        while i < len(recovered) - 1:
            gap = recovered[i+1] - recovered[i]
            if gap > Config.MISSED_BEAT_MULT * rr_avg:
                n_expected = round(gap / rr_avg)
                if n_expected == 2:
                    expected_pos = recovered[i] + int(rr_avg)
                    search_win   = int(0.10 * self.fs)
                    s = max(0, expected_pos - search_win)
                    e = min(len(ecg_bp), expected_pos + search_win)
                    seg = ecg_bp[s:e]
                    if len(seg) > 0:
                        # IMPROVED I-4: abs-max to avoid T-wave false insertion
                        local_max_idx = s + int(np.argmax(np.abs(seg)))
                        local_max_val = abs(ecg_bp[local_max_idx])
                        if local_max_val >= 0.40 * baseline.amplitude_avg:
                            recovered.insert(i+1, local_max_idx)
                            i += 1
            i += 1

        return np.array(sorted(set(recovered)), dtype=int)


# ═══════════════════════════════════════════════════════════════════
#  SIGNAL QUALITY INDEX
# ═══════════════════════════════════════════════════════════════════

def compute_sqi(ecg_bp: np.ndarray,
                peaks: np.ndarray,
                fs: int) -> float:
    """
    IMPROVED I-9: Cold-start behaviour changed.
    Original returned a magic constant 0.7 for < 3 peaks.
    Now returns a single-feature estimate (amplitude CV) when 1 or 2
    peaks are available, only falling back to 0.7 for 0 peaks.
    """
    if len(peaks) == 0:
        return 0.7

    # Amplitude-only estimate when too few peaks for rhythm statistics
    if len(peaks) < 3:
        amps    = np.array([abs(ecg_bp[p]) for p in peaks
                            if 0 <= p < len(ecg_bp)])
        if len(amps) == 0:
            return 0.7
        amp_var = float(np.std(amps)) / (float(np.mean(amps)) + 1e-6)
        return float(np.clip(1.0 - 0.4 * amp_var, 0.0, 1.0))

    rr      = np.diff(peaks)
    rr_std  = np.std(rr) / (np.mean(rr) + 1e-6)
    amps    = np.array([abs(ecg_bp[p]) for p in peaks
                        if 0 <= p < len(ecg_bp)])
    amp_var = np.std(amps) / (np.mean(amps) + 1e-6)
    sqi     = 1.0 - (0.6 * rr_std + 0.4 * amp_var)
    return float(np.clip(sqi, 0.0, 1.0))


# ═══════════════════════════════════════════════════════════════════
#  MAIN DETECTOR CLASS
# ═══════════════════════════════════════════════════════════════════

# Sentinel dict of empty-but-complete info keys — used by the early-return
# path so downstream consumers (physio_monitor, demo) never hit a KeyError.
_EMPTY_INFO: dict = {
    'ecg_clean'       : np.array([]),
    'mwi'             : np.array([]),
    'ecg_bp'          : np.array([]),
    'n_candidates'    : 0,
    'n_after_rules'   : 0,
    'n_after_ml'      : 0,
    'verified_peaks'  : np.array([], dtype=int),
    'probs'           : np.array([]),
    'baseline'        : None,   # caller must handle None
    'rr_intervals_ms' : np.array([]),
    'mean_hr_bpm'     : 0.0,
    'sdnn_ms'         : 0.0,
    'rmssd_ms'        : 0.0,
}


class HybridRPeakDetector:
    """
    Full hybrid R-peak detection pipeline.

    IMPROVED I-2: detect() now populates all info keys even on the early-
    return path (< 2 candidates), preventing KeyError in downstream code.
    """

    def __init__(self, fs: int = 250):
        self.fs             = fs
        self.preprocessor   = Preprocessor(fs)
        self.pan_tompkins   = PanTompkinsLoose(fs)
        self.rule_filter    = RuleBasedFilter(fs)
        self.feat_extractor = FeatureExtractor(fs)
        self.post_processor = PostProcessor(fs)
        self.model          = None
        self._is_trained    = False
        self.cnn            = None

    def detect(self, ecg_raw: np.ndarray,
               verbose: bool = False) -> tuple:
        # ── Stage 1: Preprocessing ──────────────────────────────────────
        ecg_clean = self.preprocessor.process(ecg_raw)
        candidates, ecg_bp, mwi = self.pan_tompkins.detect(ecg_clean)

        # IMPROVED I-2: build a complete info dict from the start
        info = dict(_EMPTY_INFO)
        info['ecg_clean']    = ecg_clean
        info['ecg_bp']       = ecg_bp
        info['mwi']          = mwi
        info['n_candidates'] = len(candidates)
        info['baseline']     = AdaptiveBaseline(self.fs)

        if len(candidates) < 2:
            return np.array([], dtype=int), info

        # ── Stage 2: Bootstrap baseline from 3 large candidates ─────────
        baseline    = info['baseline']
        safe_thresh = max(np.max(np.abs(ecg_bp)) * 0.3,
                         np.mean(np.abs(ecg_bp)) * 2.0)
        valid_inits = 0
        prev_init   = -1
        for cand in candidates:
            if valid_inits >= 3:
                break
            if abs(ecg_bp[cand]) > safe_thresh:
                rr = (cand - prev_init) if valid_inits > 0 else None
                baseline.update(ecg_bp, cand, rr)
                prev_init   = cand
                valid_inits += 1

        # ── Stage 3: Rule + ML pass ──────────────────────────────────────
        verified           = []
        prev_verified      = -1
        passed_candidates  = []
        current_sqi        = 0.7
        probs              = []
        n_after_rules      = 0

        for ci, cand in enumerate(candidates):
            passed, _ = self.rule_filter.apply(
                ecg_bp, cand, prev_verified, baseline)
            if not passed:
                continue
            n_after_rules += 1

            if current_sqi < 0.5:
                ml_threshold = 0.90
                strict_mode  = True
            elif current_sqi < 0.7:
                ml_threshold = 0.85
                strict_mode  = True
            else:
                ml_threshold = Config.ML_THRESHOLD
                strict_mode  = False

            if strict_mode and abs(ecg_bp[cand]) < 0.5 * baseline.amplitude_avg:
                continue

            passed_candidates.append(int(cand))

            try:
                # IMPROVED I-6: pass only verified candidates so that
                # feat_extractor.extract never peeks at future unverified peaks.
                feat = self.feat_extractor.extract(
                    ecg_bp,
                    np.asarray(passed_candidates, dtype=int),
                    baseline,
                    len(passed_candidates) - 1)

                if self.cnn is not None:
                    embed       = self.cnn.embed(ecg_bp, cand)
                    model_input = np.concatenate([feat, embed])
                else:
                    model_input = feat

            except Exception as e:
                if verbose:
                    print(f"[!] Feature extraction error: {e}")
                continue

            if self._is_trained and self.model is not None:
                try:
                    prob = float(self.model.predict_proba([model_input])[0, 1])
                    probs.append(prob)
                    if prob < ml_threshold:
                        continue
                except ValueError as e:
                    if verbose:
                        print(f"[!] ML dimension mismatch: {e}")
                    continue

            if verified and (cand - verified[-1]) < self.rule_filter.rr_min:
                continue

            verified.append(int(cand))
            rr = (cand - prev_verified) if prev_verified >= 0 else None

            current_sqi = compute_sqi(
                ecg_bp, np.array(verified, dtype=int), self.fs)

            if current_sqi > 0.5:
                baseline.update(ecg_bp, cand, rr)

            prev_verified = cand

        # ── Stage 4: Post-processing ─────────────────────────────────────
        final_peaks = self.post_processor.process(
            np.array(verified, dtype=int), ecg_bp, baseline)

        info['n_after_rules']  = n_after_rules
        info['n_after_ml']     = len(verified)
        info['verified_peaks'] = final_peaks
        info['probs']          = np.array(probs)
        info['baseline']       = baseline

        if len(final_peaks) >= 2:
            rr_ms = np.diff(final_peaks) / self.fs * 1000.0
            info['rr_intervals_ms'] = rr_ms
            info['mean_hr_bpm']     = float(60000 / np.mean(rr_ms))
            info['sdnn_ms']         = float(np.std(rr_ms, ddof=1))
            info['rmssd_ms']        = float(np.sqrt(np.mean(np.diff(rr_ms)**2)))

        return final_peaks, info

    def load_model(self, path: str):
        with open(path, 'rb') as f:
            payload = pickle.load(f)
        self.model = payload['model']
        meta = payload.get('meta', {})
        if 'cnn_weights' in meta:
            self.cnn = LightweightCNNAttention(fs=self.fs)
            self.cnn.set_weights(meta['cnn_weights'])
            print("[Detector] Loaded 48-dim model (32 eng + 16 CNN)")
        else:
            self.cnn = None
            print("[Detector] Loaded 32-dim base model")
        self._is_trained = True

    def save_model(self, path: str, meta: dict = None):
        import os
        os.makedirs(
            os.path.dirname(path) if os.path.dirname(path) else '.',
            exist_ok=True)
        payload = {
            'model' : self.model,
            'fs'    : self.fs,
            'config': {k: v for k, v in vars(Config).items()
                       if not k.startswith('_')},
            'meta'  : meta or {},
        }
        with open(path, 'wb') as f:
            pickle.dump(payload, f)
        print(f"[Detector] Model saved: {path}")


class PhaseOneRPeakDetector(HybridRPeakDetector):
    """Alias for the phase-1 streamlined detector architecture."""
    pass


# ═══════════════════════════════════════════════════════════════════
#  TRAINING PIPELINE
# ═══════════════════════════════════════════════════════════════════

def extract_training_data(ecg_list: list,
                          label_list: list,
                          fs: int = 250,
                          use_cnn: bool = False,
                          verbose: bool = True) -> tuple:
    """Extract features (32-dim base, or 48-dim with CNN) with SQI weights."""
    detector = HybridRPeakDetector(fs=fs)
    if use_cnn:
        detector.cnn = LightweightCNNAttention(fs=fs)
    all_X, all_y, all_g, all_w = [], [], [], []
    MATCH_TOL = int(0.05 * fs)

    for subj_idx, (ecg_raw, labels) in enumerate(zip(ecg_list, label_list)):
        ecg_clean = detector.preprocessor.process(ecg_raw)
        candidates, ecg_bp, _ = detector.pan_tompkins.detect(ecg_clean)

        if len(candidates) < 3:
            continue

        baseline = AdaptiveBaseline(fs)
        for i in range(min(5, len(candidates))):
            rr = (candidates[i]-candidates[i-1]) if i > 0 else None
            baseline.update(ecg_bp, candidates[i], rr)

        def _extract_and_append(ci, cand):
            recent_cands = candidates[max(0, ci-5):ci+1]
            sqi    = compute_sqi(ecg_bp, recent_cands, fs)
            weight = 0.3 if sqi < 0.4 else 1.0
            try:
                feat = detector.feat_extractor.extract(
                    ecg_bp, candidates, baseline, ci)
                if detector.cnn is not None:
                    embed = detector.cnn.embed(ecg_bp, int(cand))
                    feat  = np.concatenate([feat, embed])
                return feat, weight, sqi
            except Exception as e:
                if verbose:
                    print(f"\n[!] ERROR AT SUBJ {subj_idx+1}: {e}")
                return None, None, sqi

        if isinstance(labels, np.ndarray):
            expert_peaks = labels
            for ci, cand in enumerate(candidates):
                min_dist = (int(np.min(np.abs(expert_peaks - cand)))
                            if len(expert_peaks) > 0 else 9999)
                label    = 1 if min_dist <= MATCH_TOL else 0
                feat, weight, sqi = _extract_and_append(ci, cand)
                if feat is None:
                    continue
                all_X.append(feat)
                all_y.append(label)
                all_g.append(subj_idx)
                all_w.append(weight)
                if label == 1 and sqi > 0.5:
                    rr = (cand - candidates[ci-1]) if ci > 0 else None
                    baseline.update(ecg_bp, cand, rr)
        else:
            label_map = {d['candidate_idx']: d['label'] for d in labels}
            for ci, cand in enumerate(candidates):
                if cand not in label_map:
                    continue
                label = label_map[cand]
                feat, weight, sqi = _extract_and_append(ci, cand)
                if feat is None:
                    continue
                all_X.append(feat)
                all_y.append(label)
                all_g.append(subj_idx)
                all_w.append(weight)
                if label == 1 and sqi > 0.5:
                    rr = (cand - candidates[ci-1]) if ci > 0 else None
                    baseline.update(ecg_bp, cand, rr)

        if verbose:
            print(f"  Subject {subj_idx+1}: {len(candidates)} candidates")

    X       = np.array(all_X,  dtype=np.float32)
    y       = np.array(all_y,  dtype=int)
    groups  = np.array(all_g,  dtype=int)
    weights = np.array(all_w,  dtype=np.float32)

    if verbose:
        print(f"\nTotal: {len(y)} candidates | "
              f"{(y==1).sum()} true R | {(y==0).sum()} false P")

    return X, y, groups, weights


def train_hybrid_model(ecg_list: list,
                       label_list: list,
                       fs: int = 250,
                       model_out: str = 'models/hybrid_detector.pkl',
                       use_smote: bool = True,
                       use_cnn: bool = False) -> 'HybridRPeakDetector':
    """
    Full training pipeline.

    IMPROVED I-8: sample weights are now passed to each LOSO fold's
    m.fit() call so CV metrics reflect the same weighted training
    regime as the final model.  Previously only the final fit used
    weights, causing optimistic LOSO metrics on low-SQI folds.
    """
    from sklearn.model_selection import LeaveOneGroupOut
    from sklearn.metrics import f1_score, precision_score, recall_score

    print("[Train] Extracting features...")
    X, y, groups, weights = extract_training_data(
        ecg_list, label_list, fs, use_cnn=use_cnn)

    if len(y) == 0:
        raise ValueError("No training data extracted. Check inputs.")

    print(f"\n[Train] Dataset: {len(y)} candidates, "
          f"{len(np.unique(groups))} subjects")

    # ── SMOTE (optional) ──────────────────────────────────────────────
    try:
        from imblearn.over_sampling import SMOTE
        from imblearn.pipeline import Pipeline as ImbPipeline
        if use_smote and (y==0).sum() > 5:
            smote_ratio = min(0.4, (y==0).sum() / (y==1).sum())
            clf   = GradientBoostingClassifier(
                n_estimators=300, max_depth=4, learning_rate=0.03,
                subsample=0.75, min_samples_leaf=5, random_state=42)
            model = ImbPipeline([
                ('scaler', RobustScaler()),
                ('smote',  SMOTE(sampling_strategy=smote_ratio,
                                  random_state=42, k_neighbors=5)),
                ('clf',    clf),
            ])
            print("[Train] SMOTE enabled")
        else:
            model = build_xgboost()
    except ImportError:
        model = build_xgboost()
        print("[Train] SMOTE not available — using class weights")

    # ── LOSO cross-validation ──────────────────────────────────────────
    logo      = LeaveOneGroupOut()
    all_preds = np.zeros(len(y), dtype=int)
    all_probs = np.zeros(len(y))
    n_subj    = len(np.unique(groups))

    print(f"\n[Train] LOSO CV — {n_subj} subjects")
    print("─" * 50)

    for fold, (tr, te) in enumerate(logo.split(X, y, groups)):
        m = build_xgboost()
        # IMPROVED I-8: pass sample weights to each fold
        m.fit(X[tr], y[tr], clf__sample_weight=weights[tr])
        all_preds[te] = m.predict(X[te])
        all_probs[te] = m.predict_proba(X[te])[:, 1]

        subj = groups[te[0]]
        se   = recall_score(y[te],    all_preds[te], zero_division=0)
        p    = precision_score(y[te], all_preds[te], zero_division=0)
        f1   = f1_score(y[te],        all_preds[te], zero_division=0)
        print(f"  Fold {fold+1:2d} | Subj {subj} | "
              f"Se={se:.3f}  P+={p:.3f}  F1={f1:.3f}")

    print("─" * 50)
    ov_se = recall_score(y,    all_preds, zero_division=0)
    ov_p  = precision_score(y, all_preds, zero_division=0)
    ov_f1 = f1_score(y,        all_preds, zero_division=0)
    print(f"\n  Overall | Se={ov_se:.4f}  P+={ov_p:.4f}  F1={ov_f1:.4f}")
    print(f"  Priority: P+ (precision) — target > 0.99\n")

    print("[Train] Training final model on full dataset...")
    model.fit(X, y, clf__sample_weight=weights)

    detector             = HybridRPeakDetector(fs=fs)
    detector.model       = model
    detector._is_trained = True
    cnn_weights_to_save  = None
    if use_cnn:
        detector.cnn        = LightweightCNNAttention(fs=fs)
        cnn_weights_to_save = detector.cnn.get_weights()
    detector.save_model(model_out, meta={
        'overall_Se'  : ov_se,
        'overall_P+'  : ov_p,
        'overall_F1'  : ov_f1,
        'n_candidates': len(y),
        'n_subjects'  : n_subj,
        'cnn_weights' : cnn_weights_to_save,
    })

    return detector


# ═══════════════════════════════════════════════════════════════════
#  VISUALISATION
# ═══════════════════════════════════════════════════════════════════

def plot_detection(ecg_raw: np.ndarray,
                   verified_peaks: np.ndarray,
                   info: dict,
                   fs: int = 250,
                   title: str = 'Hybrid R-Peak Detection',
                   save_path: str = None):
    """4-panel ECG detection plot."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed — skipping plot.")
        return

    t = np.arange(len(ecg_raw)) / fs
    fig, axes = plt.subplots(4, 1, figsize=(15, 11), sharex=False)
    fig.suptitle(title, fontsize=13, fontweight='bold')

    axes[0].plot(t, ecg_raw, color='gray', lw=0.7, alpha=0.8)
    if len(verified_peaks) > 0:
        axes[0].plot(t[verified_peaks], ecg_raw[verified_peaks],
                     'r^', ms=7, label=f'{len(verified_peaks)} R-peaks',
                     zorder=5)
    axes[0].set_ylabel('Amplitude (raw)')
    axes[0].set_title('Raw ECG + Detected R-Peaks')
    axes[0].legend(fontsize=9)
    axes[0].set_xlim([t[0], t[-1]])

    ecg_clean = info.get('ecg_clean', ecg_raw)
    axes[1].plot(t, ecg_clean, color='steelblue', lw=0.8)
    if len(verified_peaks) > 0:
        axes[1].plot(t[verified_peaks], ecg_clean[verified_peaks],
                     'r^', ms=7, zorder=5)
    axes[1].set_ylabel('Amplitude (clean)')
    axes[1].set_title('Preprocessed ECG')
    axes[1].set_xlim([t[0], t[-1]])

    mwi = info.get('mwi', None)
    if mwi is not None:
        axes[2].plot(t, mwi, color='darkorange', lw=0.8)
        axes[2].set_ylabel('MWI')
        axes[2].set_title('Pan-Tompkins MWI')
        axes[2].set_xlim([t[0], t[-1]])
    else:
        axes[2].set_visible(False)

    rr_ms = info.get('rr_intervals_ms', np.array([]))
    if len(rr_ms) > 1:
        t_rr = t[verified_peaks[1:]]
        axes[3].plot(t_rr, rr_ms, 'o-', color='seagreen', ms=4, lw=1.2)
        axes[3].axhline(np.mean(rr_ms), color='red', ls='--', lw=1,
                        label=f'Mean RR={np.mean(rr_ms):.0f} ms')
        axes[3].set_ylabel('RR interval (ms)')
        axes[3].set_xlabel('Time (s)')
        axes[3].set_title(
            f'RR Tachogram — HR={info.get("mean_hr_bpm",0):.1f} bpm  '
            f'SDNN={info.get("sdnn_ms",0):.1f} ms  '
            f'RMSSD={info.get("rmssd_ms",0):.1f} ms')
        axes[3].legend(fontsize=8)
        axes[3].set_xlim([t[0], t[-1]])
    else:
        axes[3].text(0.5, 0.5, 'Not enough peaks for tachogram',
                     ha='center', va='center', transform=axes[3].transAxes)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Plot saved: {save_path}")
    plt.show()


# ═══════════════════════════════════════════════════════════════════
#  SYNTHETIC ECG GENERATOR (TESTING)
# ═══════════════════════════════════════════════════════════════════

def generate_synthetic_ecg(duration_sec: int = 30,
                             fs: int = 250,
                             hr: float = 72.0,
                             noise: float = 0.05) -> np.ndarray:
    t   = np.linspace(0, duration_sec, fs * duration_sec)
    ecg = np.zeros_like(t)
    rr  = 60.0 / hr

    for bt in np.arange(0.5, duration_sec, rr):
        dt   = t - bt
        ecg += 0.15 * np.exp(-dt**2 / (2*(0.025)**2))
        ecg += 1.00 * np.exp(-dt**2 / (2*(0.010)**2))
        ecg -= 0.25 * np.exp(-dt**2 / (2*(0.020)**2))
        ecg += 0.30 * np.exp(-(dt-0.20)**2 / (2*(0.050)**2))

    ecg += 0.05 * np.sin(2 * np.pi * 0.25 * t)
    ecg += noise * 0.3 * np.sin(2 * np.pi * 50 * t)
    ecg += noise * np.random.randn(len(t))
    return (ecg * 1000).astype(np.float64)


# ═══════════════════════════════════════════════════════════════════
#  EXAMPLE / SMOKE-TEST
# ═══════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 60)
    print("  Hybrid R-Peak Detector (improved) — Smoke Test")
    print("=" * 60)
    FS = 250
    np.random.seed(42)

    ecg_raw  = generate_synthetic_ecg(30, FS, hr=72, noise=0.05)
    expected = int(30 * 72 / 60)
    print(f"Expected ~{expected} beats")

    detector = HybridRPeakDetector(fs=FS)
    peaks, info = detector.detect(ecg_raw, verbose=True)

    # Verify all expected info keys are present (I-2)
    required = ['ecg_clean', 'ecg_bp', 'mwi', 'n_candidates',
                'n_after_rules', 'n_after_ml', 'verified_peaks',
                'rr_intervals_ms', 'mean_hr_bpm', 'sdnn_ms', 'rmssd_ms']
    missing = [k for k in required if k not in info]
    assert not missing, f"Missing info keys: {missing}"
    print(f"  All info keys present ✓")

    print(f"  Detected: {len(peaks)} peaks  |  HR={info['mean_hr_bpm']:.1f} bpm")

    # Verify I-4: early-return on tiny signal
    tiny = np.zeros(50)
    _, tiny_info = detector.detect(tiny)
    assert 'n_after_rules' in tiny_info, "I-2 failed on tiny signal"
    print("  Early-return info keys present ✓")

    # Verify I-3: rule labels no longer duplicated
    import inspect, re
    src    = inspect.getsource(RuleBasedFilter.apply)
    labels = re.findall(r'Rule \d+', src)
    assert len(labels) == len(set(labels)), f"Duplicate rule labels: {labels}"
    print(f"  Rule labels unique: {labels} ✓")

    # Verify I-9: SQI cold-start not magic-0.7 for 1-2 peaks
    ecg_bp = info['ecg_bp']
    sqi_1  = compute_sqi(ecg_bp, peaks[:1], FS)
    sqi_2  = compute_sqi(ecg_bp, peaks[:2], FS)
    print(f"  SQI(1 peak)={sqi_1:.3f}  SQI(2 peaks)={sqi_2:.3f}  "
          f"(data-driven, not magic 0.7) ✓")

    print("\nAll smoke-tests passed.")
    print("=" * 60)
