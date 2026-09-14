import json
import time
from collections import Counter
from datetime import date, timedelta

from garminconnect import Garmin
try:
    from garminconnect import GarminConnectTooManyRequestsError
except ImportError:  # exposed under .exceptions in some library versions
    from garminconnect.exceptions import GarminConnectTooManyRequestsError

from .db import connect
from .envfile import require

# Endpoints that only ever return data for recent dates, and cost one request
# per day. Fetching them across the full 365-day window would triple the request
# count for nothing (and Garmin rate-limits hard), so keep them to a short tail.
DEEP_DAYS = 45
MAX_CONSECUTIVE_429 = 5   # after this many rate-limited days in a row, stop and say so


def _client() -> Garmin:
    g = Garmin(require("GARMIN_EMAIL"), require("GARMIN_PASSWORD"))
    g.login()
    return g


FAILED = object()   # sentinel: the call raised (as opposed to returning nothing)


def _try(fn, what: str, fails: Counter, default=None):
    """One endpoint call. A rate limit propagates (the whole day is skipped); any other
    failure is counted under `what` and returns FAILED, so a broken endpoint shows up in
    the end-of-sync summary instead of silently leaving a column empty."""
    try:
        return fn() or default
    except GarminConnectTooManyRequestsError:
        raise
    except Exception as e:
        fails[f"{what}: {type(e).__name__}"] += 1
        return FAILED


def _first(payload):
    """Several endpoints return either a dict or a single-element list of dicts."""
    if isinstance(payload, list):
        return payload[0] if payload else {}
    return payload or {}


def _vo2max(payload) -> float | None:
    generic = (_first(payload) or {}).get("generic") or {}
    return generic.get("vo2MaxPreciseValue") or generic.get("vo2MaxValue")


def _readiness(payload) -> float | None:
    return (_first(payload) or {}).get("score")


def _race_series(g: Garmin, start: str, end: str) -> dict:
    """One bulk call for the whole window, keyed by calendar date."""
    try:
        rows = g.get_race_predictions(startdate=start, enddate=end, _type="daily")
    except Exception:
        return {}
    rows = rows if isinstance(rows, list) else [rows]
    return {r["calendarDate"]: r for r in rows if r.get("calendarDate")}


def _overnight_hr_floor(g: Garmin, ds: str, sdto: dict) -> int | None:
    """True overnight HR floor from the intraday stream: mean of the lowest ~2%
    of samples inside the sleep window (falls back to the whole day if the sleep
    window is missing). More faithful than Garmin's restingHeartRate, which a
    slow-to-settle first half of the night inflates."""
    hr = g.get_heart_rates(ds) or {}
    samples = [v for v in (hr.get("heartRateValues") or []) if v and v[1]]
    if not samples:
        return None
    gs, ge = sdto.get("sleepStartTimestampGMT"), sdto.get("sleepEndTimestampGMT")
    if gs and ge:
        win = [v for v in samples if gs <= v[0] <= ge]
        if win:
            samples = win
    vals = sorted(v[1] for v in samples)
    lo = vals[:max(1, len(vals) // 50)]
    return round(sum(lo) / len(lo))


def sync(days: int = 365, deep_days: int = DEEP_DAYS, hr_floor_days: int = 21) -> int:
    """Pull Garmin daily metrics.

    Sleep/HRV populate only on nights the watch was worn, and HRV only on a
    watch that supports HRV status (Forerunner 265 onwards — see CLAUDE.md).
    VO2max and training readiness are fetched for the last `deep_days` only; the
    derived overnight HR floor (one intraday call/day) for the last
    `hr_floor_days` only. Both are COALESCE-preserved for older dates.
    """
    g = _client()
    today = date.today()
    oldest = today - timedelta(days=days - 1)
    races = _race_series(g, oldest.isoformat(), today.isoformat())

    rows = []
    fails, skipped, run_of_429 = Counter(), 0, 0
    for i in range(days):
        d = today - timedelta(days=i)
        ds = d.isoformat()
        # On a 429 skip the whole date rather than upsert a partial row — a
        # rate-limited empty response is NOT "no data for this day" (COALESCE keeps
        # what an earlier sync stored). Back off, and give up after a run of them
        # rather than burning through every remaining date in seconds.
        try:
            stats = _try(lambda: g.get_stats(ds), "stats", fails, {})
            if stats is FAILED:
                skipped += 1    # no stats, no row: an all-null row would blank the day's raw_json
                continue
            hrv = _try(lambda: g.get_hrv_data(ds), "hrv", fails, {})
            sleep = _try(lambda: g.get_sleep_data(ds), "sleep", fails, {})
            mm, tr = {}, {}
            if i < deep_days:
                mm = _try(lambda: g.get_max_metrics(ds), "max_metrics", fails, {})
                tr = _try(lambda: g.get_training_readiness(ds), "training_readiness", fails, {})
            hrv, sleep, mm, tr = ({} if v is FAILED else v for v in (hrv, sleep, mm, tr))
            sdto = sleep.get("dailySleepDTO", {}) or {}
            # True overnight HR floor, derived from the intraday trajectory — cleaner
            # than Garmin's restingHeartRate scalar, which a slow-to-settle night
            # inflates. Recent window only (one call/day); older floors are preserved
            # by COALESCE. The gap (resting_hr - hr_floor) measures early-night load.
            hr_floor = None
            if i < hr_floor_days:
                hr_floor = _try(lambda: _overnight_hr_floor(g, ds, sdto), "hr_floor", fails)
                hr_floor = None if hr_floor is FAILED else hr_floor
        except GarminConnectTooManyRequestsError:
            fails["rate limited (day skipped)"] += 1
            skipped += 1
            run_of_429 += 1
            if run_of_429 >= MAX_CONSECUTIVE_429:
                print(f"  garmin_sync: rate limited {run_of_429} days running at {ds}; "
                      f"stopping here (earlier dates keep their stored values). Re-run later.",
                      flush=True)
                break
            time.sleep(min(15 * run_of_429, 60))
            continue
        run_of_429 = 0
        hsum = hrv.get("hrvSummary") or {}
        race = races.get(ds, {})
        rows.append({
            "date": ds,
            "sleep_score": (sdto.get("sleepScores", {}) or {}).get("overall", {}).get("value"),
            "sleep_duration_s": sdto.get("sleepTimeSeconds"),
            "deep_sleep_s": sdto.get("deepSleepSeconds"),
            "rem_sleep_s": sdto.get("remSleepSeconds"),
            "light_sleep_s": sdto.get("lightSleepSeconds"),
            "awake_sleep_s": sdto.get("awakeSleepSeconds"),
            # Overnight respiration (breaths/min). One of the few objective
            # illness / alcohol / overreaching flags available, and it needs no
            # subjective input — a steady baseline with a rise as the signal.
            "resp_sleep_avg": sdto.get("averageRespirationValue"),
            "resp_sleep_low": sdto.get("lowestRespirationValue"),
            "resp_sleep_high": sdto.get("highestRespirationValue"),
            "resting_hr": stats.get("restingHeartRate"),
            "hr_floor": hr_floor,
            "hrv_overnight": hsum.get("lastNightAvg"),
            "hrv_weekly_avg": hsum.get("weeklyAvg"),  # Garmin's own running baseline
            "hrv_status": hsum.get("status"),
            "body_battery_high": stats.get("bodyBatteryHighestValue"),
            "body_battery_low": stats.get("bodyBatteryLowestValue"),
            "stress_avg": stats.get("averageStressLevel"),
            "steps": stats.get("totalSteps"),
            "vo2max": _vo2max(mm),
            "training_readiness": _readiness(tr),
            "race_5k_s": race.get("time5K"),
            "race_10k_s": race.get("time10K"),
            "raw_json": json.dumps(
                {"stats": stats, "hrv": hrv, "sleep": sleep,
                 "max_metrics": mm, "training_readiness": tr, "race": race},
                default=str,
            ),
        })

    with connect() as conn:
        _upsert(conn, rows)
    if fails:
        print(f"  garmin_sync: {len(rows)} of {days} days upserted, {skipped} skipped; "
              + ", ".join(f"{k} x{v}" for k, v in fails.most_common()), flush=True)
    return len(rows)


# Columns that must never be blanked by a null on re-sync. Two reasons a value
# can be null: (a) sparse-by-design — Garmin only fills it on some days (a
# qualifying run, a worn night, once the HRV baseline exists), and a short
# deep_days window must not erase what a deeper sync stored; (b) occasionally-null
# daily values — Garmin's algorithm sometimes returns no restingHeartRate / steps
# / body-battery for a day whose other stats are present, and overwriting a
# previously-good value with that null corrupts trends (the resting_hr - hr_floor
# gap especially). COALESCE(new, old) keeps the old value when the new is null,
# and still applies a genuine new (non-null) value, so corrections still work.
SPARSE = ("hrv_overnight", "hrv_weekly_avg", "hrv_status", "vo2max",
          "training_readiness", "race_5k_s", "race_10k_s", "hr_floor",
          "sleep_score", "sleep_duration_s", "deep_sleep_s", "rem_sleep_s",
          "light_sleep_s", "awake_sleep_s",
          "resp_sleep_avg", "resp_sleep_low", "resp_sleep_high",
          "resting_hr", "steps", "body_battery_high", "body_battery_low",
          "stress_avg")


def _upsert(conn, rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0])
    updates = ", ".join(
        f"{c}=COALESCE(excluded.{c}, garmin_daily.{c})" if c in SPARSE else f"{c}=excluded.{c}"
        for c in cols if c != "date"
    )
    conn.executemany(
        f"INSERT INTO garmin_daily ({', '.join(cols)}) "
        f"VALUES ({', '.join(':' + c for c in cols)}) "
        f"ON CONFLICT(date) DO UPDATE SET {updates}",
        rows,
    )
