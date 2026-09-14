"""Export the per-night overnight HRV trace to a durable JSONL.

recovery_log.jsonl keeps the nightly HRV *average*; this stores the full overnight
*trace* — the ~90-100 five-minute HRV readings across the night — which shows
*when* parasympathetic recovery happened (a suppressed early night after an evening
workout that rebounds before waking reads very differently from the average alone)
and can't be reconstructed once Garmin's (unofficial) API is gone. Only a watch that
records overnight HRV (Forerunner 255+/265 generation) produces it; the readings live
inside garmin_daily.raw_json['hrv']['hrvReadings'],
a gitignored API-rebuilt cache.

data/hrv_trace.jsonl — one line per night:
  {"date","offset_h","start_local","night_avg","weekly_avg","high_5min","status",
   "readings":[[min_from_start, hrv_ms], ...]}

MERGES with the existing file (never drops an archived night). Idempotent.

Run: .venv/bin/python scripts/build_hrv_trace.py
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "fitness.db"
OUT = ROOT / "data" / "hrv_trace.jsonl"


def _gmt(v):
    """Reading timestamps come as GMT ISO strings (sometimes epoch ms)."""
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000, timezone.utc)
    s = str(v).replace("Z", "").split(".")[0]
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def trace_for(hrv):
    """Compact trace dict for one night, or None if no HRV readings."""
    reads = hrv.get("hrvReadings") or []
    if not reads:
        return None
    gs, ls = hrv.get("startTimestampGMT"), hrv.get("startTimestampLocal")
    if isinstance(gs, (int, float)) and isinstance(ls, (int, float)):
        off_h = round((ls - gs) / 3600000)   # device local offset from GMT
    else:
        try:  # fall back to a reading's own GMT-vs-Local gap
            off_h = round((_gmt(reads[0].get("readingTimeLocal"))
                           - _gmt(reads[0].get("readingTimeGMT"))).total_seconds() / 3600)
        except Exception:
            off_h = 0
    pts = []
    for r in reads:
        v, t = r.get("hrvValue"), r.get("readingTimeGMT")
        if v is None or t is None:
            continue
        # GMT stamp -> local wall-clock: convert ONCE. Never double-shift a
        # pre-shifted *Local field (see CLAUDE.md).
        pts.append((_gmt(t) + timedelta(hours=off_h), v))
    if not pts:
        return None
    pts.sort()
    t0 = pts[0][0]
    hsum = hrv.get("hrvSummary") or {}
    return {
        "offset_h": off_h,
        "start_local": t0.strftime("%Y-%m-%dT%H:%M:%S"),
        "night_avg": hsum.get("lastNightAvg"),
        "weekly_avg": hsum.get("weeklyAvg"),
        "high_5min": hsum.get("lastNight5MinHigh"),
        "status": hsum.get("status"),
        "readings": [[round((t - t0).total_seconds() / 60, 1), v] for t, v in pts],
    }


def load_existing():
    if not OUT.exists():
        return {}
    return {r["date"]: r for r in
            (json.loads(l) for l in OUT.read_text().splitlines() if l.strip())}


def main():
    merged = load_existing()
    added = 0
    con = sqlite3.connect(DB)
    for date_, raw in con.execute(
            "SELECT date, raw_json FROM garmin_daily WHERE raw_json IS NOT NULL ORDER BY date"):
        if date_ in merged:
            continue                       # keep the archived copy; traces don't change
        try:
            hrv = (json.loads(raw) or {}).get("hrv") or {}
        except (json.JSONDecodeError, TypeError):
            continue
        t = trace_for(hrv)
        if t:
            merged[date_] = {"date": date_, **t}
            added += 1

    with open(OUT, "w") as f:
        for d in sorted(merged):
            f.write(json.dumps(merged[d]) + "\n")
    print(f"Wrote {OUT.relative_to(ROOT)} ({len(merged)} nights, {added} new)")


if __name__ == "__main__":
    main()
