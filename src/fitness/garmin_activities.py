"""Cache per-run Garmin metrics that the Strava feed drops.

Strava carries HR, pace and cadence for runs, but NOT running power or the
running-dynamics family (ground contact time, vertical oscillation/ratio,
stride length). Those exist only in Garmin Connect, and only from the
Forerunner 265 onward (running power is native; the dynamics need the watch,
and ground-contact/oscillation need the HRM-Pro strap — so they're sparse).

This pulls the recent Garmin activity list, fetches the detail for run-type
activities not already cached, and stores the metrics keyed by Garmin id.
build_run_log.py joins them onto Strava runs by start-time.

Only NEW activities get a detail fetch (one API request each), so re-running is
cheap and idempotent.
"""
import json
import os
from datetime import datetime, timezone

from garminconnect import Garmin

from .db import connect
from .envfile import require

# summaryDTO key -> our column. Everything sparse by nature (older watches /
# strap-less runs leave dynamics null); we store whatever is present.
FIELDS = {
    "averagePower": "avg_power",
    "normalizedPower": "norm_power",
    "maxPower": "max_power",
    "averageRunCadence": "avg_run_cadence",
    "maxRunCadence": "max_run_cadence",
    "groundContactTime": "ground_contact_ms",
    "groundContactBalanceLeft": "gct_balance_left",
    "strideLength": "stride_length_cm",
    "verticalOscillation": "vertical_oscillation_cm",
    "verticalRatio": "vertical_ratio",
    "avgRespirationRate": "avg_respiration",
    "trainingEffect": "aerobic_te",
    "anaerobicTrainingEffect": "anaerobic_te",
    "trainingEffectLabel": "te_label",
    "activityTrainingLoad": "training_load",
}


def _client() -> Garmin:
    g = Garmin(require("GARMIN_EMAIL"), require("GARMIN_PASSWORD"))
    g.login()
    return g


def _extract(full: dict, garmin_id: int) -> dict:
    s = full.get("summaryDTO", {}) or {}
    row = {"garmin_id": garmin_id,
           "start_time_gmt": s.get("startTimeGMT"),
           "activity_type": (full.get("activityTypeDTO") or {}).get("typeKey")}
    for src, col in FIELDS.items():
        row[col] = s.get(src)
    return row


def sync(limit: int = 200, refresh: bool = False) -> int:
    """Cache metrics for recent run-type Garmin activities. Returns rows written.

    `refresh=True` re-fetches even already-cached activities (use after a metric
    is added); otherwise only new activities cost an API call.

    The listing is one request whatever the limit, and only uncached runs cost a
    detail call, so ask for plenty. The old default of 30 counted walks and gym
    sessions too, so on a rebuild from scratch it would have refilled only the last
    couple of weeks of runs and build_run_log.py would then have stripped the power
    and dynamics block from every older run in the durable log.
    """
    g = _client()
    try:
        acts = g.get_activities(0, limit, activitytype="running")   # every running subtype
    except TypeError:   # an older garminconnect without the activitytype argument
        acts = g.get_activities(0, limit)
    runs = [a for a in acts if "run" in ((a.get("activityType") or {}).get("typeKey") or "")]

    with connect() as conn:
        have = {r[0] for r in conn.execute("SELECT garmin_id FROM garmin_activities")}
    todo = [a for a in runs if refresh or a["activityId"] not in have]

    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for a in todo:
        gid = a["activityId"]
        try:
            full = g.get_activity(gid) or {}
        except Exception:
            continue
        row = _extract(full, gid)
        row["fetched_at"] = stamp
        row["raw_json"] = json.dumps(full.get("summaryDTO", {}), default=str)
        rows.append(row)

    if rows:
        cols = list(rows[0])
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "garmin_id")
        sql = (f"INSERT INTO garmin_activities ({', '.join(cols)}) "
               f"VALUES ({', '.join(':' + c for c in cols)}) "
               f"ON CONFLICT(garmin_id) DO UPDATE SET {updates}")
        with connect() as conn:
            conn.executemany(sql, rows)
    return len(rows)


def by_start_minute() -> dict:
    """Cached metrics keyed by 'YYYY-MM-DDTHH:MM' (GMT) for joining to Strava."""
    out = {}
    with connect() as conn:
        conn.row_factory = None
        cur = conn.execute("SELECT * FROM garmin_activities")
        names = [d[0] for d in cur.description]
        for r in cur.fetchall():
            rec = dict(zip(names, r))
            st = rec.get("start_time_gmt")
            if st:
                out[st[:16]] = rec   # 'YYYY-MM-DDTHH:MM'
    return out


def _target(s: dict) -> str:
    kind = (s.get("targetType") or {}).get("workoutTargetTypeKey")
    a, b = s.get("targetValueOne"), s.get("targetValueTwo")
    if kind in (None, "no.target"):
        return ""
    if kind == "power.zone" and a and b:
        return f"{a:.0f}-{b:.0f} W"
    if kind == "heart.rate.zone":
        return f"{a:.0f}-{b:.0f} bpm" if a and b else f"HR zone {s.get('zoneNumber')}"
    if kind == "pace.zone" and a and b:   # m/s; the faster bound is the larger value
        pace = lambda v: f"{int(1000 / v // 60)}:{int(1000 / v % 60):02d}"
        return f"{pace(b)}-{pace(a)} /km"
    if kind == "cadence" and a and b:
        return f"{a:.0f}-{b:.0f} spm"
    return f"{kind} {a}-{b}"


def _steps(steps: list, indent: str = "") -> list[str]:
    lines = []
    for s in steps:
        if s.get("type") == "RepeatGroupDTO":
            lines.append(f"{indent}{s.get('numberOfIterations')}x:")
            lines += _steps(s.get("workoutSteps") or [], indent + "  ")
            continue
        cond = (s.get("endCondition") or {}).get("conditionTypeKey")
        v = s.get("endConditionValue")
        end = ("lap button" if not v else f"{v / 60:g} min" if cond == "time"
               else f"{v / 1000:g} km" if cond == "distance" else f"{cond} {v:g}")
        kind = (s.get("stepType") or {}).get("stepTypeKey", "step")
        parts = [kind, end, _target(s), s.get("description") or ""]
        lines.append(indent + ", ".join(p for p in parts if p))
    return lines


def scheduled(date: str) -> list[dict]:
    """The workouts scheduled in Garmin Connect for one day ('YYYY-MM-DD'), each with its
    steps written out, so a run is judged against what was planned for that day. The
    calendar's month view also carries the neighbouring weeks, hence the filter on date."""
    g = _client()
    year, month = int(date[:4]), int(date[5:7])
    out = []
    for item in g.get_scheduled_workouts(year, month).get("calendarItems", []):
        if item.get("itemType") != "workout" or item.get("date") != date:
            continue
        w = g.get_workout_by_id(item["workoutId"])
        steps = [line for seg in w.get("workoutSegments") or []
                 for line in _steps(seg.get("workoutSteps") or [])]
        out.append({"title": item.get("title"), "workout_id": item["workoutId"],
                    "description": w.get("description"), "steps": steps})
    return out
