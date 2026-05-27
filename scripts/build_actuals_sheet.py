"""Generate the 'Session Log (actuals)' CSV from strength_log.jsonl.

Two sections:
  1. PER-EXERCISE PROGRESSION — heaviest working set per exercise per session date
  2. FULL SET-BY-SET LOG — every set, chronological

Run: python scripts/build_actuals_sheet.py
Outputs: data/actuals_log.csv  (upload to Google Sheets as a new/refreshed sheet)
"""
import json, csv, io
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "data" / "strength_log.jsonl"

# Display-name aliases: canonicalise variant names so each lift is ONE row in the
# views, without editing the JSONL (which stays the verbatim source of truth).
# Add new aliases here as variants appear.
ALIASES = {
    "pallof press (band)": "pallof press",
    "face pull": "face pulls",
    "seated 45-degree row (machine, chest-supported alt)": "chest-supported row",
    "high-cable single-arm lateral raise": "high-cable lateral raise",
}
def canon(name):
    return ALIASES.get(name, name)

entries = []
with open(LOG) as f:
    for line in f:
        line = line.strip()
        if line:
            entries.append(json.loads(line))
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
ex_history = defaultdict(dict)   # exercise -> {date: "reps×weight"}
for e in entries:
    d = e["session_date"]
    for ex in e["exercises"]:
        name = canon(ex["name"])
        reps, wt, nsets = top_set(ex)
        if wt is not None:
            cell = f"{wt:g}×{reps}×{nsets}" if reps else f"{wt:g}"
        elif reps is not None:
            cell = f"BW×{reps}×{nsets}"
        else:
            cell = "BW"
        # if same exercise twice in a session keep the heavier
        prev = ex_history[name].get(d)
        ex_history[name][d] = cell if prev is None else prev  # first wins; rare dup

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
