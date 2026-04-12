"""
pipeline_config.py — MaternalGuard Central Control Panel
==========================================================
Toggle features, ML models, dashboard metrics, and hardware
settings from this single file. server.py reads everything here.

Usage:
    Edit the values below → restart server.py → changes take effect.

    PIPELINE_MODE = "simple"     ← lightweight SignalProcessor (default)
    PIPELINE_MODE = "advanced"   ← full PhysioMonitor + ML pipeline
"""


# ═══════════════════════════════════════════════════════════════════
#  1. PIPELINE MODE
# ═══════════════════════════════════════════════════════════════════
#
#  "simple"   → server.py's built-in SignalProcessor
#               Fast, low CPU, no ML dependencies at runtime.
#               Good for demos, testing, and when hardware is limited.
#
#  "advanced" → PhysioMonitor from physio_monitor.py
#               Hybrid R-peak detector + GBM beat classifier +
#               multi-modal fusion + beat validation.
#               Higher accuracy, higher CPU. Needs trained models.

PIPELINE_MODE = "advanced"


# ═══════════════════════════════════════════════════════════════════
#  2. SIGNAL INPUTS
# ═══════════════════════════════════════════════════════════════════
#  Toggle which sensors are expected from the ESP32.
#  If a sensor is disabled, its metrics are hidden from the dashboard.

ENABLE_ECG = True       # AD8232 via ADS1115
ENABLE_PPG = True       # MAX30102 IR channel
ENABLE_PPG_RED = False  # MAX30102 Red channel (needed for SpO2)


# ═══════════════════════════════════════════════════════════════════
#  3. ML MODELS (only matter when PIPELINE_MODE = "advanced")
# ═══════════════════════════════════════════════════════════════════
#  When OFF, the system falls back to rule-based classification.
#  These models were trained via mitdb_training_pipeline.py on MIT-BIH.
#
#  Your models/ directory contains:
#    hybrid_detector_mitdb.pkl       (752 KB) — GBM R-peak verifier
#    beat_validator_morphology.pkl   (751 KB) — GBM beat classifier (32-dim)
#    r_peak_verifier_BASE.pkl        (158 KB) — XGBoost verifier (needs xgboost)
#
#  ESP32 firmware file:
#    firmware/xgboost_rpeak_verifier.h — C-transpiled XGBoost (100 trees,
#      32 float inputs -> sigmoid confidence). No xgboost lib needed on device.

ENABLE_GBM_CLASSIFIER  = False   # GBM R-peak verifier (Pan-Tompkins + GBM)
ENABLE_CNN_VALIDATOR   = False   # Lightweight CNN morphology embeddings
ENABLE_BEAT_VALIDATOR  = False   # BeatValidator (valid / noise / PVC)
ENABLE_XGBOOST_VERIFIER = False  # XGBoost R-peak verifier (needs: pip install xgboost)

# Model file paths — matched to actual filenames in models/
MODEL_DIR              = "models/"
GBM_MODEL_PATH         = "models/hybrid_detector_mitdb.pkl"
BEAT_VALIDATOR_PATH    = "models/beat_validator_morphology.pkl"
XGBOOST_VERIFIER_PATH = "models/r_peak_verifier_BASE.pkl"
BASELINE_PATH          = "models/personal_baseline.pkl"

# Auto-load models on startup (if files exist)
AUTO_LOAD_MODELS       = True


# ═══════════════════════════════════════════════════════════════════
#  4. DASHBOARD METRICS — Toggle what shows on the frontend
# ═══════════════════════════════════════════════════════════════════
#  Set False to hide a panel from the dashboard.
#  The backend still computes disabled metrics (just doesn't send them).
#  Set to None to skip computation entirely (saves CPU).

class Dashboard:
    """Which panels / metrics are visible on the dashboard."""

    # ── Waveforms ─────────────────────────────────────────────────
    ECG_WAVEFORM        = True    # Live ECG trace
    PPG_WAVEFORM        = True    # Live PPG trace

    # ── Core Vitals ───────────────────────────────────────────────
    HEART_RATE          = True    # HR (bpm) from R-peaks
    HRV_TIME_DOMAIN     = True    # RMSSD, SDNN, pNN50, mean RR
    HRV_FREQ_DOMAIN     = True    # LF, HF, LF/HF ratio

    # ── Maternal-Specific ─────────────────────────────────────────
    STRESS_SCORE        = True    # 0-100 stress index + autonomic state
    FETAL_WELLBEING     = True    # Maternal HRV coherence proxy
    CONTRACTION_MONITOR = True    # PPG amplitude periodicity
    PREECLAMPSIA_RISK   = True    # 6-factor rule-based PE scoring

    # ── Cardiovascular ────────────────────────────────────────────
    PTT_BP_PROXY        = True    # Pulse Transit Time → BP estimate
    SPO2_PERFUSION      = True    # SpO2 + Perfusion Index (needs Red PPG)
    PPG_MORPHOLOGY      = True    # SPD, DPD, PWD, Augmentation Index

    # ── Respiratory ───────────────────────────────────────────────
    BREATHING_RATE      = True    # PPG respiratory modulation

    # ── Session ───────────────────────────────────────────────────
    SESSION_TIMELINE    = True    # Autonomic state transitions
    SESSION_DATA        = True    # CSV download button


# ═══════════════════════════════════════════════════════════════════
#  5. SIGNAL PROCESSING PARAMETERS
# ═══════════════════════════════════════════════════════════════════

class SignalParams:
    """Tunable signal processing constants."""

    SAMPLING_RATE       = 250     # Hz — must match ESP32 firmware

    # ECG filtering
    ECG_BP_LOW          = 0.5     # Hz — bandpass low cutoff
    ECG_BP_HIGH         = 40.0    # Hz — bandpass high cutoff
    ECG_NOTCH_FREQ      = 50.0   # Hz — mains noise (50 India, 60 US)
    ECG_NOTCH_Q         = 30.0   # Notch quality factor

    # PPG filtering
    PPG_BP_LOW          = 0.5     # Hz — pulsatile band
    PPG_BP_HIGH         = 4.0     # Hz
    PPG_BREATH_LOW      = 0.1     # Hz — respiratory band
    PPG_BREATH_HIGH     = 0.5     # Hz

    # Buffers
    ROLLING_WINDOW_SEC  = 5       # seconds of data kept in memory
    HRV_BUFFER_BEATS    = 200     # max RR intervals stored
    PTT_BUFFER_SIZE     = 30      # median PTT window

    # Calibration
    CALIB_DURATION_SEC  = 60      # baseline calibration length
    CALIB_SQI_THRESHOLD = 0.6     # minimum signal quality for calibration
    CALIB_MIN_RR        = 10      # min valid RR intervals needed

    # Stress
    STRESS_EMA_ALPHA    = 0.15    # EMA smoothing for stress score
    HIGH_STRESS_ALERT_SEC = 120   # alert after this many seconds of stress > 70


# ═══════════════════════════════════════════════════════════════════
#  6. NETWORK & HARDWARE
# ═══════════════════════════════════════════════════════════════════

UDP_IP          = "0.0.0.0"
UDP_PORT        = 5005
WEB_PORT        = 8080
SECRET_KEY      = "maternalguard_secret"


# ═══════════════════════════════════════════════════════════════════
#  7. DATA LOGGING
# ═══════════════════════════════════════════════════════════════════

ENABLE_CSV_LOGGING  = True      # Write session data to CSV
CSV_FLUSH_INTERVAL  = 250       # Flush every N updates (~5s at 50ms)
LOG_DIRECTORY       = "."       # Where to save session CSVs


# ═══════════════════════════════════════════════════════════════════
#  8. DEVELOPER / DEBUG
# ═══════════════════════════════════════════════════════════════════

VERBOSE             = False     # Extra console output
DEBUG_SOCKETIO      = False     # Flask-SocketIO debug mode
PRINT_METRICS_EVERY = 0        # Print metrics to console every N updates (0=off)


# ═══════════════════════════════════════════════════════════════════
#  HELPER: get active metric list (used by server.py to filter payload)
# ═══════════════════════════════════════════════════════════════════

def get_enabled_metrics() -> dict:
    """
    Returns a dict of metric_group → enabled (bool).
    server.py uses this to decide what to compute and emit.
    """
    return {
        "ecg_wave":        Dashboard.ECG_WAVEFORM and ENABLE_ECG,
        "ppg_wave":        Dashboard.PPG_WAVEFORM and ENABLE_PPG,
        "heart_rate":      Dashboard.HEART_RATE,
        "hrv_time":        Dashboard.HRV_TIME_DOMAIN,
        "hrv_freq":        Dashboard.HRV_FREQ_DOMAIN,
        "stress":          Dashboard.STRESS_SCORE,
        "fetal":           Dashboard.FETAL_WELLBEING,
        "contraction":     Dashboard.CONTRACTION_MONITOR,
        "pe_risk":         Dashboard.PREECLAMPSIA_RISK,
        "ptt":             Dashboard.PTT_BP_PROXY,
        "spo2":            Dashboard.SPO2_PERFUSION and ENABLE_PPG_RED,
        "ppg_morphology":  Dashboard.PPG_MORPHOLOGY and ENABLE_PPG,
        "breathing":       Dashboard.BREATHING_RATE,
        "timeline":        Dashboard.SESSION_TIMELINE,
        "session_data":    Dashboard.SESSION_DATA,
    }


def print_config():
    """Print current configuration to console."""
    m = get_enabled_metrics()
    on  = [k for k, v in m.items() if v]
    off = [k for k, v in m.items() if not v]

    print("=" * 60)
    print("  MaternalGuard Pipeline Configuration")
    print("=" * 60)
    print(f"  Pipeline    : {PIPELINE_MODE.upper()}")
    print(f"  ECG         : {'ON' if ENABLE_ECG else 'OFF'}")
    print(f"  PPG (IR)    : {'ON' if ENABLE_PPG else 'OFF'}")
    print(f"  PPG (Red)   : {'ON' if ENABLE_PPG_RED else 'OFF'}")
    print(f"  GBM Model   : {'ON' if ENABLE_GBM_CLASSIFIER else 'OFF'}")
    print(f"  CNN Model   : {'ON' if ENABLE_CNN_VALIDATOR else 'OFF'}")
    print(f"  Beat Valid. : {'ON' if ENABLE_BEAT_VALIDATOR else 'OFF'}")
    print(f"  XGBoost     : {'ON' if ENABLE_XGBOOST_VERIFIER else 'OFF'}")
    print(f"  CSV Logging : {'ON' if ENABLE_CSV_LOGGING else 'OFF'}")
    print(f"  Sampling    : {SignalParams.SAMPLING_RATE} Hz")
    print(f"  Notch       : {SignalParams.ECG_NOTCH_FREQ} Hz")
    print(f"  Server      : http://localhost:{WEB_PORT}")
    print()
    print(f"  Dashboard ON  : {', '.join(on)}")
    print(f"  Dashboard OFF : {', '.join(off) if off else 'none'}")
    print("=" * 60)


# ── Auto-print on import (if run directly) ────────────────────────
if __name__ == "__main__":
    print_config()
