"""Re-derive structured garmin_daily columns from the raw_json blob already in
the DB. No API calls: every field here is present in raw_json today but was
never parsed into its own column (respiration, Garmin's weekly-HRV baseline) or
was left null on older rows (light/awake sleep seconds).

Idempotent: sets each column to its raw_json value, which matches the existing
value where one is present, so it is safe to re-run. Run after a schema change
(it applies migrations first) or any time you want the columns reconciled with
raw_json. Rebuild the durable recovery log afterwards:

    .venv/bin/python scripts/backfill_garmin_columns.py
    .venv/bin/python scripts/build_recovery_log.py
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fitness.db import DB_PATH, init  # noqa: E402


def main():
    init()  # apply pending column migrations before backfilling
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    n_resp = n_wk = n_light = 0
    for row in con.execute(
        "SELECT date, raw_json, light_sleep_s, awake_sleep_s FROM garmin_daily"
    ).fetchall():
        if not row["raw_json"]:
            continue
        j = json.loads(row["raw_json"])
        sdto = (j.get("sleep") or {}).get("dailySleepDTO") or {}
        hsum = (j.get("hrv") or {}).get("hrvSummary") or {}
        upd = {}
        if sdto.get("averageRespirationValue") is not None:
            upd["resp_sleep_avg"] = sdto.get("averageRespirationValue")
            upd["resp_sleep_low"] = sdto.get("lowestRespirationValue")
            upd["resp_sleep_high"] = sdto.get("highestRespirationValue")
            n_resp += 1
        if hsum.get("weeklyAvg") is not None:
            upd["hrv_weekly_avg"] = hsum.get("weeklyAvg")
            n_wk += 1
        # Only fill light/awake where currently null (recover the 76-night gap);
        # never overwrite a value already present.
        if row["light_sleep_s"] is None and sdto.get("lightSleepSeconds") is not None:
            upd["light_sleep_s"] = sdto.get("lightSleepSeconds")
            upd["awake_sleep_s"] = sdto.get("awakeSleepSeconds")
            n_light += 1
        if upd:
            sets = ", ".join(f"{k}=?" for k in upd)
            con.execute(
                f"UPDATE garmin_daily SET {sets} WHERE date=?",
                (*upd.values(), row["date"]),
            )
    con.commit()
    print(f"Backfilled from raw_json: respiration {n_resp} nights, "
          f"weekly-HRV {n_wk} nights, light/awake {n_light} previously-null nights")


if __name__ == "__main__":
    main()
