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

# --- Personal zone boundaries used by the durable log builders ---------------
# Karvonen, HRmax 195 / RHR ~42, per TRAINING_PLAN.md. SINGLE SOURCE OF TRUTH:
# build_run_log.py and build_cardio_log.py both import these — do NOT re-hardcode
# the numbers anywhere else, or the logs will silently drift apart. If the lab
# lactate test lands, recalibrate to the measured LT1/LT2 HERE and rebuild.
# >>> SET YOUR OWN <<< upper bpm bound of each zone (example values shown — Karvonen,
# HRmax 195 / RHR ~42). Replace with your numbers, or derive from compute_zones().
PERSONAL_ZONE_UPPERS = [(134, "Z1"), (148, "Z2"), (163, "Z3"), (178, "Z4")]  # above -> Z5
ZONE_NAMES = ("Z1", "Z2", "Z3", "Z4", "Z5")


def zone(hr: float) -> str:
    for upper, name in PERSONAL_ZONE_UPPERS:
        if hr <= upper:
            return name
    return "Z5"


def zone_dist(hr, t) -> dict | None:
    """{Z1..Z5: seconds} weighted by sample dt, or None if no usable HR."""
    if not hr or not t or len(hr) != len(t):
        return None
    tz = {z: 0 for z in ZONE_NAMES}
    for i in range(1, len(t)):
        tz[zone(hr[i])] += t[i] - t[i - 1]
    return tz if sum(tz.values()) else None


def drift_quarters(hr) -> list | None:
    """Mean HR per quarter of the session (cardiac-drift signal)."""
    if not hr:
        return None
    q = len(hr) // 4
    if q == 0:
        return None
    return [round(sum(seg) / len(seg), 1) for seg in
            (hr[i * q:(i + 1) * q] if i < 3 else hr[3 * q:] for i in range(4))]


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
