import json
import os
from datetime import date, timedelta

from garminconnect import Garmin

from .db import connect


def _client() -> Garmin:
    g = Garmin(os.environ["GARMIN_EMAIL"], os.environ["GARMIN_PASSWORD"])
    g.login()
    return g


def sync(days: int = 365) -> int:
    """Pull Garmin daily metrics. Sleep/HRV populate only on nights the watch
    was worn.
    """
    g = _client()
    today = date.today()
    rows = []
    for i in range(days):
        d = today - timedelta(days=i)
        ds = d.isoformat()
        try:
            stats = g.get_stats(ds) or {}
        except Exception:
            continue
        try:
            hrv = g.get_hrv_data(ds) or {}
        except Exception:
            hrv = {}
        try:
            sleep = g.get_sleep_data(ds) or {}
        except Exception:
            sleep = {}
        sdto = sleep.get("dailySleepDTO", {}) or {}
        rows.append((
            ds,
            (sdto.get("sleepScores", {}) or {}).get("overall", {}).get("value"),
            sdto.get("sleepTimeSeconds"),
            sdto.get("deepSleepSeconds"),
            sdto.get("remSleepSeconds"),
            stats.get("restingHeartRate"),
            (hrv.get("hrvSummary") or {}).get("lastNightAvg"),
            stats.get("bodyBatteryHighestValue"),
            stats.get("bodyBatteryLowestValue"),
            stats.get("averageStressLevel"),
            stats.get("totalSteps"),
            json.dumps({"stats": stats, "hrv": hrv, "sleep": sleep}, default=str),
        ))
    with connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO garmin_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)
