"""Maintain the durable bodyweight log.

`data/weight_log.jsonl` is the committed source of truth (one line per weigh-in).
It carries two kinds of entry:
  - source="garmin" — weigh-ins pulled from Garmin Connect (he sometimes enters
    them there); this script syncs any it doesn't already have.
  - source="manual" — appended by Claude when he just tells me a number in chat.
    These are preserved; the sync never overwrites or drops them.

Merged by date (an existing local entry wins, so manual notes survive), sorted,
rewritten wholesale. Idempotent — safe to re-run.

Bodyweight matters here for two live things: the protein target (g/kg) and
power-to-weight on runs. Keep it current.

Run: .venv/bin/python scripts/build_weight_log.py
"""
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
OUT = ROOT / "data" / "weight_log.jsonl"

PROTEIN_LO, PROTEIN_HI = 1.8, 2.2   # g/kg/day — vegetarian + concurrent training


def load_existing():
    if not OUT.exists():
        return {}
    return {r["date"]: r for r in
            (json.loads(l) for l in OUT.read_text().splitlines() if l.strip())}


def fetch_garmin(start="2020-01-01"):
    """Weigh-ins from Garmin Connect, keyed by date. Empty dict on any failure —
    the local log is the source of truth and must survive an API outage."""
    try:
        from garminconnect import Garmin
        g = Garmin(os.environ["GARMIN_EMAIL"], os.environ["GARMIN_PASSWORD"])
        g.login()
        bc = g.get_body_composition(start, date.today().isoformat()) or {}
    except Exception as e:
        print(f"  (Garmin fetch failed: {type(e).__name__} — keeping local log only)")
        return {}
    out = {}
    for e in bc.get("dateWeightList") or []:
        d, w = e.get("calendarDate"), e.get("weight")
        if not d or not w:
            continue
        kg = w / 1000 if w > 1000 else w   # Garmin stores grams
        out[d] = {"date": d, "weight_kg": round(kg, 1), "source": "garmin",
                  "notes": None}
    return out


def main():
    existing = load_existing()
    garmin = fetch_garmin()
    merged = dict(garmin)
    merged.update(existing)   # a local entry wins — never clobber a manual note

    rows = [merged[d] for d in sorted(merged)]
    with open(OUT, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    new = len(set(garmin) - set(existing))
    print(f"Wrote {OUT.relative_to(ROOT)} ({len(rows)} weigh-ins, {new} new from Garmin)")
    if rows:
        latest = rows[-1]
        w = latest["weight_kg"]
        print(f"  latest: {w} kg on {latest['date']} ({latest['source']})")
        print(f"  -> protein target {w * PROTEIN_LO:.0f}-{w * PROTEIN_HI:.0f} g/day "
              f"({PROTEIN_LO}-{PROTEIN_HI} g/kg)")
        if len(rows) > 1:
            first = rows[0]
            print(f"  trend: {first['weight_kg']} kg ({first['date']}) "
                  f"-> {w} kg ({latest['date']})  = {w - first['weight_kg']:+.1f} kg")


if __name__ == "__main__":
    main()
