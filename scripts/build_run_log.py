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
import json, csv, io, sqlite3, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "fitness.db"

# HR zones + drift come from fitness.zones — the single source of truth, shared
# with build_cardio_log.py so the two logs can never drift apart.
sys.path.insert(0, str(ROOT / "src"))
from fitness.zones import zone, zone_dist, drift_quarters  # noqa: E402

con = sqlite3.connect(DB)
stream_ids = {r[0] for r in con.execute("SELECT DISTINCT activity_id FROM activity_streams")}

# Garmin-only per-run metrics (running power + dynamics), joined to Strava runs
# by GMT start-minute. Sparse: only FR265 runs have power/dynamics; strap-less
# runs lack ground-contact/oscillation; older watches have cadence at most.
def _load_garmin_metrics():
    try:
        cols = [d[1] for d in con.execute("PRAGMA table_info(garmin_activities)")]
    except sqlite3.OperationalError:
        return {}
    out = {}
    for r in con.execute("SELECT * FROM garmin_activities"):
        rec = dict(zip(cols, r))
        st = rec.get("start_time_gmt")
        if st:
            out[st[:16]] = rec   # 'YYYY-MM-DDTHH:MM'
    return out

garmin_by_min = _load_garmin_metrics()

def _rnd(x, n=1):
    return round(x, n) if isinstance(x, (int, float)) else None

def _garmin_block(start):
    gm = garmin_by_min.get((start or "")[:16])
    if not gm:
        return None
    block = {
        "avg_power": _rnd(gm["avg_power"], 0),
        "norm_power": _rnd(gm["norm_power"], 0),
        "max_power": _rnd(gm["max_power"], 0),
        "avg_cadence_spm": _rnd(gm["avg_run_cadence"], 0),
        "max_cadence_spm": _rnd(gm["max_run_cadence"], 0),
        "ground_contact_ms": _rnd(gm["ground_contact_ms"], 0),
        "gct_balance_left": _rnd(gm["gct_balance_left"]),
        "stride_length_cm": _rnd(gm["stride_length_cm"]),
        "vertical_oscillation_cm": _rnd(gm["vertical_oscillation_cm"]),
        "vertical_ratio": _rnd(gm["vertical_ratio"]),
        "avg_respiration": _rnd(gm["avg_respiration"]),
        "aerobic_te": _rnd(gm["aerobic_te"]),
        "anaerobic_te": _rnd(gm["anaerobic_te"]),
        "te_label": gm["te_label"],
        "training_load": _rnd(gm["training_load"], 0),
    }
    # Drop entirely-empty blocks (old cadence-only rows still carry cadence).
    return block if any(v is not None for v in block.values()) else None

rows = con.execute(
    "SELECT id, start_time, name, distance_m, moving_time_s, elevation_gain_m, "
    "avg_hr, max_hr, raw_json FROM activities WHERE sport='Run' ORDER BY start_time"
).fetchall()


# Collapse duplicate recordings of one session. A treadmill run can upload TWICE
# to Strava — once from the Garmin watch, once from the machine's own app (e.g.
# Technogym). Group runs starting within 3 min; keep a Garmin recording as the
# base (consistent HR + the start-minute key that joins running power), and adopt
# a machine twin's belt distance as the RELIABLE treadmill distance (the machine
# measures it; the watch only guesses).
def _is_machine(raw, name):
    ext = (raw.get("external_id") or "").lower()
    nm = (name or "").lower()
    return ext.endswith(".tcx") or "excite" in nm or "run 7000" in nm or "technogym" in nm
def _is_garmin(raw):
    return "garmin" in (raw.get("external_id") or "").lower()

_parsed = [(r, json.loads(r[8]) if r[8] else {}) for r in rows]
_groups = []
for r, raw in _parsed:
    st = datetime.fromisoformat(r[1])
    for g in _groups:
        if abs((st - datetime.fromisoformat(g[0][0][1])).total_seconds()) <= 180:
            g.append((r, raw)); break
    else:
        _groups.append([(r, raw)])

deduped = []   # (row, machine_dist_m or None, dup_ids)
for g in _groups:
    if len(g) == 1:
        deduped.append((g[0][0], None, [])); continue
    prim = next((x for x in g if _is_garmin(x[1])), None) or max(g, key=lambda x: x[0][4] or 0)
    tech = next((x for x in g if _is_machine(x[1], x[0][2])), None)
    machine = tech[0][3] if (tech and tech[0] is not prim[0]) else None
    dup_ids = [x[0][0] for x in g if x[0] is not prim[0]]
    deduped.append((prim[0], machine, dup_ids))

records = []
for row, machine_dist_m, dup_ids in deduped:
    aid, start, name, dist_m, mov_s, elev, avg_hr, max_hr, raw_json = row
    raw = json.loads(raw_json) if raw_json else {}
    treadmill = bool(raw.get("trainer")) or raw.get("start_latlng") is None
    date = start[:10]
    # A machine (Technogym) twin gives the true belt distance -> reliable pace.
    if machine_dist_m and treadmill:
        dist_m = machine_dist_m
    pace_reliable = (not treadmill) or bool(machine_dist_m)
    dist_km = round(dist_m / 1000, 2) if dist_m else None
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
        # Sub-1km activities are warmup jogs / accidental recordings, not runs —
        # flagged (not dropped) so consumers can exclude them from counts/volume
        # while the row stays in the durable log.
        "counts_as_run": bool(dist_km and dist_km >= 1.0),
        "moving_time_s": mov_s,
        "pace_min_km": pace,
        "pace_reliable": pace_reliable,   # True on a machine-measured (Technogym) treadmill run
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

    rec["garmin"] = _garmin_block(start)   # running power + dynamics (FR265; sparse)

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
            "Polarisation target: >=75% Z1+Z2, <=20% Z4+Z5. Treadmill pace is unreliable (flagged). "
            "Power + running dynamics need a supporting watch (Forerunner 255+/265 generation); dynamics also need a compatible strap/pod."])
w.writerow([])
w.writerow(["Date", "Name", "Treadmill", "Distance (km)", "Duration (min)",
            "Pace (min/km)", "Pace reliable", "Elev (m)", "Avg HR", "Max HR",
            "Z1%", "Z2%", "Z3%", "Z4%", "Z5%", "Z1+Z2%", "Z4+Z5%", "Drift Q1->Q4",
            "Avg Power (W)", "Norm Power (W)", "Cadence (spm)", "GCT (ms)",
            "Vert Osc (cm)", "Vert Ratio (%)", "Stride (cm)", "Aerobic TE", "Train Load"])
for r in records:
    zp = r["zones_pct"] or {}
    dq = r["drift_quarters"]
    g = r.get("garmin") or {}
    gv = lambda k: g.get(k) if g.get(k) is not None else ""
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
        gv("avg_power"), gv("norm_power"), gv("avg_cadence_spm"), gv("ground_contact_ms"),
        gv("vertical_oscillation_cm"), gv("vertical_ratio"), gv("stride_length_cm"),
        gv("aerobic_te"), gv("training_load"),
    ])

(ROOT / "data" / "run_log.csv").write_text(out.getvalue())

with_zones = sum(1 for r in records if r["zones_pct"])
with_power = sum(1 for r in records if (r.get("garmin") or {}).get("avg_power") is not None)
counted = sum(1 for r in records if r["counts_as_run"])
print("Wrote data/run_log.jsonl + data/run_log.csv")
print(f"  Runs tracked: {len(records)} ({counted} count as runs, "
      f"{len(records) - counted} sub-1km blips flagged out)")
print(f"  With HR-zone distribution: {with_zones}")
print(f"  With running power: {with_power}")
print(f"  Treadmill runs flagged: {sum(1 for r in records if r['treadmill'])}")
