import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "fitness.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    start_time TEXT NOT NULL,
    sport TEXT,
    name TEXT,
    distance_m REAL,
    moving_time_s INTEGER,
    elapsed_time_s INTEGER,
    elevation_gain_m REAL,
    avg_hr REAL,
    max_hr REAL,
    avg_power REAL,
    kilojoules REAL,
    suffer_score REAL,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS garmin_daily (
    date TEXT PRIMARY KEY,
    sleep_score REAL,
    sleep_duration_s INTEGER,
    deep_sleep_s INTEGER,
    rem_sleep_s INTEGER,
    resting_hr REAL,
    hrv_overnight REAL,
    body_battery_high REAL,
    body_battery_low REAL,
    stress_avg REAL,
    steps INTEGER,
    raw_json TEXT,
    hrv_status TEXT,
    vo2max REAL,
    training_readiness REAL,
    race_5k_s INTEGER,
    race_10k_s INTEGER
);

CREATE TABLE IF NOT EXISTS strength_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at TEXT NOT NULL,
    session_date TEXT NOT NULL,
    session_label TEXT,
    notes TEXT,
    source_line_hash TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS strength_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES strength_sessions(id),
    exercise TEXT NOT NULL,
    set_index INTEGER NOT NULL,
    reps INTEGER,
    weight_kg REAL,
    rpe REAL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS garmin_intraday (
    date TEXT NOT NULL,
    stream TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (date, stream)
);

-- Per-activity Garmin metrics the Strava feed drops: running power and running
-- dynamics (only the FR265 records these; strap-dependent dynamics are sparse).
-- Joined onto Strava runs by start-time in build_run_log.py.
CREATE TABLE IF NOT EXISTS garmin_activities (
    garmin_id INTEGER PRIMARY KEY,
    start_time_gmt TEXT,
    activity_type TEXT,
    avg_power REAL,
    norm_power REAL,
    max_power REAL,
    avg_run_cadence REAL,
    max_run_cadence REAL,
    ground_contact_ms REAL,
    gct_balance_left REAL,
    stride_length_cm REAL,
    vertical_oscillation_cm REAL,
    vertical_ratio REAL,
    avg_respiration REAL,
    aerobic_te REAL,
    anaerobic_te REAL,
    te_label TEXT,
    training_load REAL,
    fetched_at TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS activity_details (
    activity_id INTEGER PRIMARY KEY REFERENCES activities(id),
    fetched_at TEXT NOT NULL,
    description TEXT,
    gear_id TEXT,
    device_name TEXT,
    calories REAL,
    laps_json TEXT,
    best_efforts_json TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS activity_streams (
    activity_id INTEGER PRIMARY KEY REFERENCES activities(id),
    fetched_at TEXT NOT NULL,
    resolution TEXT,
    streams_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_activities_start ON activities(start_time);
CREATE INDEX IF NOT EXISTS idx_strength_sets_ex ON strength_sets(exercise);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# Columns added after the table first shipped. CREATE TABLE IF NOT EXISTS is a
# no-op on an existing DB, so they have to be ALTERed in.
MIGRATIONS = {
    "garmin_daily": [
        ("hrv_status", "TEXT"),
        ("vo2max", "REAL"),
        ("training_readiness", "REAL"),
        ("race_5k_s", "INTEGER"),
        ("race_10k_s", "INTEGER"),
        ("light_sleep_s", "INTEGER"),
        ("awake_sleep_s", "INTEGER"),
        ("hr_floor", "INTEGER"),
    ],
}


def migrate(conn: sqlite3.Connection) -> None:
    for table, cols in MIGRATIONS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        migrate(conn)
