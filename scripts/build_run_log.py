"""Build the durable run log + sheet view from the Strava-synced DB.

Runs are pulled from Strava into the (gitignored) SQLite DB. That makes Strava
the upstream source, but leaves NO durable in-repo record. This script fixes
that: it regenerates a committed `data/run_log.jsonl` (one line per run, with
computed HR-zone distribution + cardiac drift) so every run is tracked over
time independently of Strava, plus a `data/run_log.csv` view for the Google
Sheet "Fitness — Run Log".

Idempotent: rebuilds both files from the DB every run. Safe to run repeatedly.

Run: .venv/bin/python scripts/build_run_log.py
"""
import json, csv, io, sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "fitness.db"

# ── EDIT THESE: your personal HR-zone ceilings (bpm) ──────────────────────────
# These are EXAMPLE placeholders. Replace with your own zones (Karvonen/HRR from
# src/fitness/zones.py once you have data, or a lab/field test). Z3 is the
# "avoid" grey zone in a polarised model.
Z1_MAX, Z2_MAX, Z3_MAX, Z4_MAX = 134, 148, 163, 178
def zone(h):
    if h <= Z1_MAX: return "Z1"
    if h <= Z2_MAX: return "Z2"
    if h <= Z3_MAX: return "Z3"
    if h <= Z4_MAX: return "Z4"
    return "Z5"

def zone_dist(hr, t):
    """Return {Z1..Z5: seconds} weighted by sample dt, or None if no HR."""
    if not hr or not t or len(hr) != len(t):
        return None
    tz = {z: 0 for z in ("Z1", "Z2", "Z3", "Z4", "Z5")}
    for i in range(1, len(t)):
        tz[zone(hr[i])] += t[i] - t[i - 1]
    return tz if sum(tz.values()) else None

def drift_quarters(hr):
    """Mean HR per quarter (cardiac drift signal)."""
    if not hr:
        return None
    q = len(hr) // 4
    if q == 0:
        return None
    means = []
    for i in range(4):
        seg = hr[i * q:(i + 1) * q] if i < 3 else hr[3 * q:]
        means.append(round(sum(seg) / len(seg), 1))
    return means

con = sqlite3.connect(DB)
stream_ids = {r[0] for r in con.execute("SELECT DISTINCT activity_id FROM activity_streams")}

rows = con.execute(
    "SELECT id, start_time, name, distance_m, moving_time_s, elevation_gain_m, "
    "avg_hr, max_hr, raw_json FROM activities WHERE sport='Run' ORDER BY start_time"
).fetchall()

records = []
for aid, start, name, dist_m, mov_s, elev, avg_hr, max_hr, raw_json in rows:
    raw = json.loads(raw_json) if raw_json else {}
    treadmill = bool(raw.get("trainer")) or raw.get("start_latlng") is None
    date = start[:10]
    dist_km = round(dist_m / 1000, 2) if dist_m else None
    # pace min/km (UNRELIABLE for treadmill — distance is user-entered)
    pace = None
    if dist_km and mov_s:
        p = (mov_s / 60) / dist_km
        pace = f"{int(p)}:{int(round((p - int(p)) * 60)):02d}"

    rec = {
        "activity_id": aid,
        "date": date,
        "start_time": start,
        "name": name,
        "treadmill": treadmill,
        "distance_km": dist_km,
        "moving_time_s": mov_s,
        "pace_min_km": pace,
        "pace_reliable": not treadmill,   # watch treadmill speed is fiction
        "elevation_gain_m": round(elev, 1) if elev is not None else None,
        "avg_hr": round(avg_hr, 1) if avg_hr is not None else None,
        "max_hr": int(max_hr) if max_hr is not None else None,
        "zones_pct": None,
        "z1_z2_pct": None,
        "z4_z5_pct": None,
        "drift_quarters": None,
    }

    if aid in stream_ids:
        s = json.loads(con.execute(
            "SELECT streams_json FROM activity_streams WHERE activity_id=?", (aid,)
        ).fetchone()[0])
        hr, t = s.get("heartrate"), s.get("time")
        tz = zone_dist(hr, t)
        if tz:
            tot = sum(tz.values())
            rec["zones_pct"] = {z: round(100 * tz[z] / tot, 1) for z in tz}
            rec["z1_z2_pct"] = round(100 * (tz["Z1"] + tz["Z2"]) / tot, 1)
            rec["z4_z5_pct"] = round(100 * (tz["Z4"] + tz["Z5"]) / tot, 1)
        rec["drift_quarters"] = drift_quarters(hr)

    records.append(rec)

# --- Durable JSONL (committed) ---
jsonl = ROOT / "data" / "run_log.jsonl"
with open(jsonl, "w") as f:
    for r in records:
        f.write(json.dumps(r) + "\n")

# --- CSV view (sheet) ---
out = io.StringIO()
w = csv.writer(out)
w.writerow(["RUN LOG — auto-generated from the Strava-synced DB by build_run_log.py. "
            "Polarisation target: >=75% Z1+Z2, <=20% Z4+Z5. Treadmill pace is unreliable (flagged)."])
w.writerow([])
w.writerow(["Date", "Name", "Treadmill", "Distance (km)", "Duration (min)",
            "Pace (min/km)", "Pace reliable", "Elev (m)", "Avg HR", "Max HR",
            "Z1%", "Z2%", "Z3%", "Z4%", "Z5%", "Z1+Z2%", "Z4+Z5%", "Drift Q1->Q4"])
for r in records:
    zp = r["zones_pct"] or {}
    dq = r["drift_quarters"]
    w.writerow([
        r["date"], r["name"], "Y" if r["treadmill"] else "",
        r["distance_km"] or "",
        round(r["moving_time_s"] / 60, 1) if r["moving_time_s"] else "",
        r["pace_min_km"] or "", "" if r["pace_reliable"] else "NO",
        r["elevation_gain_m"] if r["elevation_gain_m"] is not None else "",
        r["avg_hr"] if r["avg_hr"] is not None else "",
        r["max_hr"] if r["max_hr"] is not None else "",
        zp.get("Z1", ""), zp.get("Z2", ""), zp.get("Z3", ""),
        zp.get("Z4", ""), zp.get("Z5", ""),
        r["z1_z2_pct"] if r["z1_z2_pct"] is not None else "",
        r["z4_z5_pct"] if r["z4_z5_pct"] is not None else "",
        " -> ".join(str(x) for x in dq) if dq else "",
    ])

(ROOT / "data" / "run_log.csv").write_text(out.getvalue())

with_zones = sum(1 for r in records if r["zones_pct"])
print("Wrote data/run_log.jsonl + data/run_log.csv")
print(f"  Runs tracked: {len(records)}")
print(f"  With HR-zone distribution: {with_zones}")
print(f"  Treadmill runs flagged: {sum(1 for r in records if r['treadmill'])}")
