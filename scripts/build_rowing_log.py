"""Build a durable rowing log from the Concept2 Logbook (API + CSV exports).

Two sources, merged and deduped on Log ID:
  1. data/concept2_csv/*.csv — season exports from log.concept2.com (Log -> Export).
     Drop a fresh export in and re-run; this is all most people need.
  2. data/concept2_api_cache.json — optional: a list of Logbook API results
     (GET /users/me/results), if you script that yourself or use pm5-force-logger's
     concept2.py. Richer, and it carries the per-split detail the CSV drops.

API rows win on conflict. Output is data/rowing_log.jsonl (committed, one JSON
object per workout, sorted by date).

Idempotent: rebuilds wholesale each run. Pace is per 500 m (Concept2 standard).
Avg HR of 0/blank is stored as null (no HR captured).

API quirks handled here:
  - `time` is in TENTHS of a second (13002 -> 1300.2 s), unlike the CSV's seconds.
  - there is no watts field; it's derived from pace via Concept2's own relation
    watts = 2.80 / (sec_per_metre)^3, validated against CSV rows to ±0.5 W.
  - `type` is lowercase ("rower"); the CSV uses "RowErg".
"""
import csv
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "concept2_csv"
API_CACHE = ROOT / "data" / "concept2_api_cache.json"
OUT = ROOT / "data" / "rowing_log.jsonl"
PM5_SESSIONS = [ROOT / "data" / "pm5" / "sessions", ROOT / "data" / "sessions"]   # pm5-force-logger output

TYPE_MAP = {"rower": "RowErg", "skierg": "SkiErg", "bike": "BikeErg"}


def _pace_500(work_time_s, distance_m):
    """Formatted M:SS.s per 500 m."""
    if not work_time_s or not distance_m:
        return None
    p = work_time_s / (distance_m / 500)
    return f"{int(p // 60)}:{p % 60:04.1f}"


def _watts(work_time_s, distance_m):
    """Concept2's power relation: watts = 2.80 / (seconds per metre)^3."""
    if not work_time_s or not distance_m:
        return None
    return round(2.80 / ((work_time_s / distance_m) ** 3))


def _from_api(r: dict) -> dict:
    """Map one API result onto the CSV-derived schema."""
    t = r.get("time")
    work_time_s = round(t / 10, 1) if t else None      # tenths -> seconds
    dist = r.get("distance")
    rest = r.get("rest_time")
    hr = (r.get("heart_rate") or {}).get("average")
    splits = ((r.get("workout") or {}).get("splits")) or []
    return {
        "log_id": int(r["id"]),
        "date": (r.get("date") or "")[:10],
        "datetime": r.get("date"),
        "description": f"{(r.get('time_formatted') or '').split('.')[0]} row".strip(),
        "type": TYPE_MAP.get(r.get("type"), (r.get("type") or "").strip()),
        "work_time_s": work_time_s,
        "work_distance_m": dist,
        "rest_time_s": round(rest / 10, 1) if rest else None,
        "pace_500m": _pace_500(work_time_s, dist),
        "stroke_rate": r.get("stroke_rate"),
        "avg_watts": _watts(work_time_s, dist),
        "avg_hr": hr or None,                           # 0 = not captured
        "total_cal": r.get("calories_total"),
        "drag_factor": r.get("drag_factor"),
        "ranked": bool(r.get("ranked")),
        "comments": r.get("comments") or None,
        # API-only extras (the CSV has none of these)
        "stroke_count": r.get("stroke_count"),
        "workout_type": r.get("workout_type"),
        "source": r.get("source"),
        # compact per-split detail: [time_s, distance_m, stroke_rate, avg_hr]
        "splits": [[round((s.get("time") or 0) / 10, 1), s.get("distance"),
                    s.get("stroke_rate"), (s.get("heart_rate") or {}).get("average")]
                   for s in splits] or None,
    }


def _pm5_sessions() -> dict:
    """pm5-force-logger session files keyed by the Logbook id they were posted as."""
    out = {}
    for d in PM5_SESSIONS:
        for f in sorted(d.glob("*.json")) if d.exists() else []:
            try:
                sess = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if sess.get("logbook_id"):
                out[int(sess["logbook_id"])] = (f, sess)
    return out


def _enrich_from_pm5(rec: dict, sess: dict, path) -> None:
    """Fill what the Logbook copy of a logger-posted row lacks: the PM5's summary reports HR as 0,
    so the API row has no average HR and no splits, though every stroke carries HR."""
    strokes = [st for st in sess.get("strokes") or [] if st.get("distance_m") is not None]
    beats = [st["hr"] for st in strokes if st.get("hr")]
    if rec.get("avg_hr") is None and beats:
        rec["avg_hr"] = round(sum(beats) / len(beats))
    summary = sess.get("summary") or {}
    n = summary.get("split_count") or 0
    if rec.get("splits") is None and n > 1 and rec.get("work_distance_m") and strokes:
        size = rec["work_distance_m"] / n           # distance splits (the logger posts only those)
        splits, prev_t = [], 0.0
        for k in range(1, n + 1):
            inside = [st for st in strokes if (k - 1) * size < st["distance_m"] <= k * size]
            if not inside:
                continue
            t_end = inside[-1]["elapsed_s"] if k < n else rec["work_time_s"]
            hrs = [st["hr"] for st in inside if st.get("hr")]
            spm = [st["spm"] for st in inside if st.get("spm")]
            splits.append([round(t_end - prev_t, 1), round(size),
                           round(sum(spm) / len(spm)) if spm else None,
                           round(sum(hrs) / len(hrs)) if hrs else None])
            prev_t = t_end
        rec["splits"] = splits or None
    rec["pm5_session"] = path.name


def _int(x):
    x = (x or "").strip()
    try:
        return int(float(x))
    except ValueError:
        return None


def _float(x):
    x = (x or "").strip()
    try:
        return float(x)
    except ValueError:
        return None


def main():
    rows = {}
    files = sorted(glob.glob(str(SRC / "*.csv")))
    for f in files:
        with open(f, newline="") as fh:
            for r in csv.DictReader(fh):
                lid = (r.get("Log ID") or "").strip()
                if not lid:
                    continue
                hr = _int(r.get("Avg Heart Rate"))
                if hr == 0:
                    hr = None  # 0 / blank = no HR captured
                date_full = (r.get("Date") or "").strip()
                rows[lid] = {
                    "log_id": int(lid),
                    "date": date_full[:10],
                    "datetime": date_full,
                    "description": (r.get("Description") or "").strip(),
                    "type": (r.get("Type") or "").strip(),
                    "work_time_s": _float(r.get("Work Time (Seconds)")),
                    "work_distance_m": _int(r.get("Work Distance")),
                    "rest_time_s": _float(r.get("Rest Time (Seconds)")),
                    "pace_500m": (r.get("Pace") or "").strip() or None,
                    "stroke_rate": _int(r.get("Stroke Rate/Cadence")),
                    "avg_watts": _int(r.get("Avg Watts")),
                    "avg_hr": hr,
                    "total_cal": _int(r.get("Total Cal")),
                    "drag_factor": _int(r.get("Drag Factor")),
                    "ranked": (r.get("Ranked") or "").strip().lower() == "yes",
                    "comments": (r.get("Comments") or "").strip() or None,
                }
    from_csv = len(rows)

    # API rows override the CSV where both exist — richer, and split-aware.
    n_api = 0
    if API_CACHE.exists():
        for r in json.loads(API_CACHE.read_text()):
            try:
                rec = _from_api(r)
            except (KeyError, TypeError, ValueError):
                continue
            rows[str(rec["log_id"])] = rec
            n_api += 1

    pm5 = _pm5_sessions()
    n_pm5 = 0
    for lid, rec in rows.items():
        if int(lid) in pm5:
            _enrich_from_pm5(rec, pm5[int(lid)][1], pm5[int(lid)][0])
            n_pm5 += 1

    out = sorted(rows.values(), key=lambda x: (x["datetime"], x["log_id"]))
    with open(OUT, "w") as fh:
        for o in out:
            fh.write(json.dumps(o) + "\n")

    dates = [o["date"] for o in out]
    total_m = sum(o["work_distance_m"] or 0 for o in out)
    print(f"Wrote {len(out)} rowing workouts -> {OUT}")
    print(f"  sources: {len(files)} CSV file(s) -> {from_csv} rows; API cache -> {n_api} rows; "
          f"{n_pm5} enriched from pm5-force-logger sessions")
    if dates:
        print(f"  date range {min(dates)} .. {max(dates)}")
    print(f"  total work distance: {total_m:,} m ({total_m/1000:.1f} km)")


if __name__ == "__main__":
    main()
