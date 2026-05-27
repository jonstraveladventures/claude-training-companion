"""Compute personal HR zones from stored streams.

Strategy:
- HRmax: 99.5th percentile of all observed HR samples (spike-resistant).
- RHR:   median of Garmin daily resting HR.
- Zones: Karvonen HRR bands — %HRR of (HRmax - RHR) added to RHR.
"""
import json

import numpy as np
import pandas as pd

from .db import connect

ZONE_BANDS_HRR = [
    ("Z1 recovery",      0.00, 0.60),
    ("Z2 endurance",     0.60, 0.70),
    ("Z3 tempo",         0.70, 0.80),
    ("Z4 threshold",     0.80, 0.90),
    ("Z5 VO2max",        0.90, 1.00),
]


def observed_hr_max(sport_filter: list[str] | None = None) -> int:
    with connect() as conn:
        rows = conn.execute(
            "SELECT a.sport, s.streams_json "
            "FROM activity_streams s JOIN activities a ON a.id = s.activity_id"
        ).fetchall()
    all_hr = []
    for sport, sj in rows:
        if sport_filter and not any(sf in (sport or "") for sf in sport_filter):
            continue
        data = json.loads(sj)
        hr = data.get("heartrate")
        if hr:
            all_hr.extend(hr)
    if not all_hr:
        return 0
    arr = np.array(all_hr)
    arr = arr[(arr > 70) & (arr < 230)]
    return int(np.percentile(arr, 99.5))


def resting_hr() -> int:
    with connect() as conn:
        df = pd.read_sql(
            "SELECT resting_hr FROM garmin_daily WHERE resting_hr IS NOT NULL", conn
        )
    if df.empty:
        return 60
    return int(df["resting_hr"].median())


def compute_zones(hr_max: int, rhr: int) -> list[dict]:
    span = hr_max - rhr
    return [
        {
            "zone": name,
            "low": int(round(rhr + lo * span)),
            "high": int(round(rhr + hi * span)),
            "pct_hrr": f"{int(lo*100)}-{int(hi*100)}%",
        }
        for name, lo, hi in ZONE_BANDS_HRR
    ]


def time_in_zones(activity_id: int, zones: list[dict]) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT streams_json FROM activity_streams WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    if not row:
        return {}
    data = json.loads(row[0])
    hr = data.get("heartrate")
    t = data.get("time")
    if not hr or not t:
        return {}
    hr = np.array(hr)
    t = np.array(t)
    dt = np.diff(t, prepend=t[0])
    out = {z["zone"]: 0 for z in zones}
    for z in zones:
        mask = (hr >= z["low"]) & (hr < z["high"] if z["zone"] != zones[-1]["zone"] else hr <= z["high"])
        out[z["zone"]] = int(dt[mask].sum())
    return out
