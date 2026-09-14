"""Generate the 'Session Log (actuals)' CSV from strength_log.jsonl.

Two sections:
  1. PER-EXERCISE PROGRESSION — heaviest working set per exercise per session date
  2. FULL SET-BY-SET LOG — every set, chronological

Run: python scripts/build_actuals_sheet.py
Outputs: data/actuals_log.csv  (upload to Google Sheets as a new/refreshed sheet)
"""
import json, csv, io, sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "data" / "strength_log.jsonl"
sys.path.insert(0, str(ROOT / "src"))
from fitness.exercise_names import canon  # noqa: E402  (one alias table for every view)

entries = []
with open(LOG) as f:
    for line in f:
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"WARN strength_log: skipped malformed line: {e}", file=sys.stderr)
# Honour corrections: a later entry with correction_of=<logged_at> supersedes that
# original entry (which is dropped). The append-only JSONL stays the source of truth.
superseded = {e.get("correction_of") for e in entries if e.get("correction_of")}
entries = [e for e in entries if e.get("logged_at") not in superseded]
entries.sort(key=lambda e: e["session_date"])

def top_set(ex):
    """Return (reps, weight, n_sets) for the heaviest weighted set, where n_sets
    is how many sets were done AT that top weight. Bodyweight: (max_reps, None, total_sets)."""
    weighted = [s for s in ex["sets"] if s.get("weight_kg") is not None]
    if not weighted:
        reps = [s.get("reps") for s in ex["sets"] if s.get("reps")]
        n = len(ex["sets"])
        return (max(reps), None, n) if reps else (None, None, n)
    top_w = max(s["weight_kg"] for s in weighted)
    at_top = [s for s in weighted if s["weight_kg"] == top_w]
    reps = max((s.get("reps") or 0) for s in at_top)
    return (reps, top_w, len(at_top))

# Collect all exercises and all dates
all_dates = sorted({e["session_date"] for e in entries})
best = defaultdict(dict)   # exercise -> {date: (weight or -1, reps or 0, n_sets)}
for e in entries:
    d = e["session_date"]
    for ex in e["exercises"]:
        name = canon(ex["name"])
        reps, wt, nsets = top_set(ex)
        # the same exercise twice on one date (two sessions): the heavier top set wins
        cand = (wt if wt is not None else -1, reps or 0, nsets)
        if d not in best[name] or cand[:2] > best[name][d][:2]:
            best[name][d] = cand


def cell(t):
    wt, reps, nsets = t
    if wt >= 0:
        return f"{wt:g}×{reps}×{nsets}" if reps else f"{wt:g}"
    return f"BW×{reps}×{nsets}" if reps else "BW"


ex_history = {name: {d: cell(t) for d, t in by_date.items()} for name, by_date in best.items()}

out = io.StringIO()
w = csv.writer(out)

w.writerow(["SESSION LOG (actuals) — auto-generated from strength_log.jsonl. Source of truth is the JSONL; this sheet is a view."])
w.writerow([])
w.writerow(["SECTION 1: PER-EXERCISE PROGRESSION (top working set: weight×reps×sets per session)"])
header = ["Exercise"] + all_dates
w.writerow(header)
# Order exercises by first appearance
first_seen = {}
for e in entries:
    for ex in e["exercises"]:
        first_seen.setdefault(canon(ex["name"]), e["session_date"])
for name in sorted(ex_history, key=lambda n: first_seen[n]):
    row = [name] + [ex_history[name].get(d, "") for d in all_dates]
    w.writerow(row)

w.writerow([])
w.writerow(["SECTION 2: FULL SET-BY-SET LOG (chronological)"])
w.writerow(["Date","Session","Exercise","Set #","Reps","Weight (kg)","RPE","Notes"])
for e in entries:
    for ex in e["exercises"]:
        for i, s in enumerate(ex["sets"], 1):
            w.writerow([
                e["session_date"],
                e.get("session_label",""),
                canon(ex["name"]),
                i,
                s.get("reps",""),
                s.get("weight_kg","") if s.get("weight_kg") is not None else "BW",
                s.get("rpe",""),
                s.get("notes", ex.get("notes","")),
            ])

csv_text = out.getvalue()
(ROOT / "data" / "actuals_log.csv").write_text(csv_text)
print(f"Wrote data/actuals_log.csv")
print(f"  Sessions: {len(entries)}")
print(f"  Exercises tracked: {len(ex_history)}")
print(f"  Date columns: {len(all_dates)}")
