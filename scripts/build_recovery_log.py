"""Export daily Garmin recovery metrics to a durable, committed JSONL.

The `garmin_daily` table (sleep, resting HR, HRV, body battery, stress, VO2max,
race predictions, training readiness) lives ONLY in the gitignored SQLite DB,
pulled through an unofficial Garmin API. Runs, strength and rowing all have a
committed JSONL export; recovery data had none — so a DB wipe or the Garmin
library breaking would lose the entire basis of the morning recovery checks.

This closes that gap: one committed line per day, same pattern as
build_run_log.py. Idempotent — rebuilds wholesale from the DB every run.

Run: .venv/bin/python scripts/build_recovery_log.py
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "fitness.db"
OUT = ROOT / "data" / "recovery_log.jsonl"

# garmin_daily column -> output key (raw_json deliberately excluded).
COLS = [
    "date", "sleep_score", "sleep_duration_s", "deep_sleep_s", "rem_sleep_s",
    "light_sleep_s", "awake_sleep_s",
    "resting_hr", "hr_floor", "hrv_overnight", "hrv_status", "body_battery_high",
    "body_battery_low", "stress_avg", "steps", "vo2max", "training_readiness",
    "race_5k_s", "race_10k_s",
]
# A row is worth keeping only if the watch actually captured something.
SIGNAL = ["resting_hr", "sleep_duration_s", "hrv_overnight", "steps",
          "body_battery_high", "vo2max"]


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    have = {r[1] for r in con.execute("PRAGMA table_info(garmin_daily)")}
    cols = [c for c in COLS if c in have]
    rows = con.execute(
        f"SELECT {', '.join(cols)} FROM garmin_daily ORDER BY date"
    ).fetchall()

    kept = 0
    with open(OUT, "w") as f:
        for r in rows:
            rec = {c: r[c] for c in cols}
            if not any(rec.get(k) is not None for k in SIGNAL):
                continue  # no-wear day, nothing to preserve
            f.write(json.dumps(rec) + "\n")
            kept += 1
    print(f"Wrote {OUT.relative_to(ROOT)}  ({kept} days with data of {len(rows)} total)")


if __name__ == "__main__":
    main()
