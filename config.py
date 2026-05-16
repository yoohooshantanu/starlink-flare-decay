"""
config.py — Central configuration for the Starlink flare-decay pipeline.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Credentials ──────────────────────────────────────────────────────────────
NASA_API_KEY = os.getenv("NASA_API", "DEMO_KEY")
SPACETRACK_EMAIL = os.getenv("SPACETRACK_EMAIL", "")
SPACETRACK_PASSWORD = os.getenv("SPACETRACK_PASSWORD", "")

# ── Date Range ───────────────────────────────────────────────────────────────
START_DATE = "2022-01-01"
END_DATE = "2024-12-31"

# ── Flare Filtering ─────────────────────────────────────────────────────────
MIN_FLARE_CLASS = "M1.0"            # Keep M1.0 and above
EARTH_DIRECTED_LON_LIMIT = 45       # degrees from disk center

# ── Satellite Sampling ───────────────────────────────────────────────────────
SHELL1_COUNT = 50                   # ~550 km, 53° inclination
SHELL2_COUNT = 50                   # ~570 km, 70° inclination
CONTROL_COUNT = 20                  # non-Starlink LEO debris at 500–600 km

SHELL1_ALT_RANGE = (540, 560)       # km
SHELL1_INC_RANGE = (52.0, 54.0)     # degrees

SHELL2_ALT_RANGE = (560, 580)       # km
SHELL2_INC_RANGE = (69.0, 71.0)     # degrees (v1.5 shell)

CONTROL_ALT_RANGE = (500, 600)      # km

# ── Decay Computation ───────────────────────────────────────────────────────
MU = 3.986004418e14                 # Earth gravitational parameter  m³/s²
R_EARTH = 6371.0                    # km
ROLLING_WINDOW_DAYS = 3             # for decay rate regression
MANEUVER_THRESHOLD = 500            # m/day altitude increase → maneuver flag

# ── Orbital Mechanics Parameters (Starlink V1.5 proxy) ──────────────────────
STARLINK_MASS = 295.0               # kg
STARLINK_AREA = 10.0                # m^2 (effective drag area)
STARLINK_CD = 2.2                   # Drag coefficient
STARLINK_B = (STARLINK_CD * STARLINK_AREA) / STARLINK_MASS  # Ballistic coeff m^2/kg

# ── Analysis Windows (days relative to flare peak) ──────────────────────────
WINDOWS = {
    "pre_flare":    (-7,   0),
    "flare_window": ( 0,  +3),
    "cme_window":   (+1,  +5),
    "recovery":     (+5, +14),
}

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
PLOT_DIR = BASE_DIR / "plots"

DATA_DIR.mkdir(exist_ok=True)
PLOT_DIR.mkdir(exist_ok=True)

FLARE_FILE       = DATA_DIR / "flare_events.json"
TLE_DB           = DATA_DIR / "tle_history.db"
DECAY_FILE       = DATA_DIR / "decay_rates.json"
ALIGNED_FILE     = DATA_DIR / "aligned_events.json"
ANALYSIS_FILE    = DATA_DIR / "analysis_results.json"

PLOT_FILES = {
    "flare_timeline":       PLOT_DIR / "01_flare_timeline.png",
    "decay_distribution":   PLOT_DIR / "02_decay_distribution.png",
    "decay_vs_flare_class": PLOT_DIR / "03_decay_vs_flare_class.png",
    "case_events":          PLOT_DIR / "04_case_events.png",
    "recovery_time":        PLOT_DIR / "05_recovery_time.png",
    "ensemble_response":    PLOT_DIR / "06_ensemble_response.png",
    "regression_residuals": PLOT_DIR / "07_regression_residuals.png",
    "lag_correlation":      PLOT_DIR / "08_lag_correlation.png",
    "env_validation":       PLOT_DIR / "09_env_validation.png",
}

REPORT_FILE = BASE_DIR / "REPORT.md"
