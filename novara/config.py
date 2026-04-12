"""
config.py — Novara Central Configuration
==========================================
All tuneable parameters in one place.
"""
import os

# ─── Paths ────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR    = os.path.join(BASE_DIR, "data")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
DB_PATH     = os.path.join(DATA_DIR, "novara.db")
KEY_PATH    = os.path.join(DATA_DIR, "novara.key")

# Ensure directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

# ─── Database ─────────────────────────────────────────────────────
SQLALCHEMY_URI = f"sqlite:///{DB_PATH}"

# ─── Signal Processing ───────────────────────────────────────────
SAMPLING_RATE      = 250          # Hz
BASELINE_DAYS_MIN  = 3            # Minimum days for baseline
BASELINE_DAYS_MAX  = 5            # Maximum days to average

# ─── Risk Thresholds ─────────────────────────────────────────────
STRESS_HIGH_THRESHOLD        = 70.0   # Score above this = high stress
STRESS_SUSTAINED_DAYS        = 3      # Consecutive days to flag
HRV_DROP_THRESHOLD_PCT       = 25.0   # % drop from baseline
HR_HIGH_THRESHOLD            = 100.0  # bpm
HR_LOW_THRESHOLD             = 55.0   # bpm
PREECLAMPSIA_HR_ELEVATION_PCT = 15.0  # % above baseline
PREECLAMPSIA_HRV_DROP_PCT    = 20.0   # % below baseline
PREECLAMPSIA_STRESS_THRESHOLD = 65.0
PREECLAMPSIA_MIN_WEEKS       = 28     # gestational weeks

# ─── Security ─────────────────────────────────────────────────────
ACCESS_TOKEN_EXPIRY_HOURS = 24

# ─── Dashboard ────────────────────────────────────────────────────
APP_NAME    = "Novara"
APP_TAGLINE = "Physiological Intelligence for Maternal Wellness"
