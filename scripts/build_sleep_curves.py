"""Export the per-night sleep-stage curves (hypnograms) to a durable JSONL.

The nightly stage *totals* live in recovery_log.jsonl; this stores the full
*shape* — every deep/light/REM/awake segment through the night — which is the
one thing that genuinely can't be reconstructed once Garmin's (unofficial) API
is gone. The intraday sleepLevels are captured inside garmin_daily.raw_json (a
gitignored, API-rebuilt cache); this pulls them out into a committed file.

`data/sleep_curves.jsonl` — one line per night:
  {"date","offset_h","start_local","end_local","segments":[[start_min,dur_min,stage],...]}
  segments are minutes from `start_local`, stage in {Deep,Light,REM,Awake}.

MERGES with the existing file (never drops a night the DB no longer holds), so
the archive only ever grows. Idempotent.

Run: .venv/bin/python scripts/build_sleep_curves.py
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "fitness.db"
OUT = ROOT / "data" / "sleep_curves.jsonl"

STAGE = {0: "Deep", 1: "Light", 2: "REM", 3: "Awake"}


def _gmt(v):
    """sleepLevels start/end come as GMT ISO strings (sometimes epoch ms)."""
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000, timezone.utc)
    s = str(v).replace("Z", "").split(".")[0]
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def curve_for(sleep):
    """Return a compact curve dict for one night, or None if no stage data."""
    sdto = sleep.get("dailySleepDTO", {}) or {}
    levels = sleep.get("sleepLevels") or []
    gs, ls = sdto.get("sleepStartTimestampGMT"), sdto.get("sleepStartTimestampLocal")
    if not levels or not gs or not ls:
        return None
    off_h = round((ls - gs) / 3600000)   # device local offset from GMT
    segs = []
    for L in levels:
        a, s, e = L.get("activityLevel"), L.get("startGMT"), L.get("endGMT")
        if a is None or not s or not e:
            continue
        # GMT stamp -> local wall-clock: convert ONCE (add the offset). Never
        # double-shift (see CLAUDE.md: *TimestampLocal is already pre-shifted).
        segs.append((_gmt(s) + timedelta(hours=off_h),
                     _gmt(e) + timedelta(hours=off_h),
                     STAGE.get(int(a), f"?{int(a)}")))
    if not segs:
        return None
    segs.sort()
    t0 = segs[0][0]
    out_segs = [[round((s - t0).total_seconds() / 60, 1),
                 round((e - s).total_seconds() / 60, 1), st] for s, e, st in segs]
    return {
        "offset_h": off_h,
        "start_local": t0.strftime("%Y-%m-%dT%H:%M:%S"),
        "end_local": segs[-1][1].strftime("%Y-%m-%dT%H:%M:%S"),
        "segments": out_segs,
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
            continue                       # keep the archived copy; curves don't change
        try:
            sleep = (json.loads(raw) or {}).get("sleep") or {}
        except (json.JSONDecodeError, TypeError):
            continue
        c = curve_for(sleep)
        if c:
            merged[date_] = {"date": date_, **c}
            added += 1

    with open(OUT, "w") as f:
        for d in sorted(merged):
            f.write(json.dumps(merged[d]) + "\n")
    print(f"Wrote {OUT.relative_to(ROOT)} ({len(merged)} nights, {added} new)")


if __name__ == "__main__":
    main()
