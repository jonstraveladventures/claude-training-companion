# Claude instructions for this project

> This file tells Claude Code how to behave in your training repo. Edit the
> `[PLACEHOLDER]` sections to your own goals, constraints, units, and timezone.

## Strength logging (mobile-friendly)

When the user describes a strength workout — whether in chat ("just did 5x5 squats at 100kg") or asks to log one — append one JSON object per line to `data/strength_log.jsonl`. Do NOT rewrite the file, only append.

### Schema

```json
{
  "logged_at": "2026-01-01T18:45:00+00:00",
  "session_date": "2026-01-01",
  "session_label": "lower day",
  "exercises": [
    {
      "name": "back squat",
      "sets": [
        {"reps": 5, "weight_kg": 100, "rpe": 7},
        {"reps": 5, "weight_kg": 100, "rpe": 7.5}
      ],
      "notes": "felt heavy on last set"
    }
  ],
  "notes": "short on time, skipped accessory work"
}
```

### Rules

- `logged_at` — current timestamp in the user's local timezone `[SET YOUR TIMEZONE]`.
- `session_date` — the date the workout happened (may differ if logged later).
- `exercise.name` — lowercase, canonical (e.g. "back squat", not "Squats"). If ambiguous, ask.
- `weight_kg` — pick one unit and stay consistent. Convert if the user gives the other.
- `rpe` — optional, 1–10. Only fill if the user mentioned or implied it.
- `maintenance` — optional boolean on an exercise (or the whole session). Set `true` for deliberately light travel/deload work so it is NOT treated as a working top set or allowed to distort the progression trend.
- If a set's reps/weight is implied ("5x5 at 100") expand to explicit set objects.
- If the user says "same as last time", read the last entry for that exercise and reuse.

### MANDATORY logging protocol (do not skip)

Logging is the single most important durable output of this project. Process:

1. **Append immediately** when the user reports a session — before any analysis.
2. **Confirm visibly** at the end with the literal line: `✓ Logged to strength_log.jsonl`.
3. **Regenerate views**: run `python scripts/build_actuals_sheet.py`.
4. **Periodic audit**: every few weeks, cross-check the JSONL against session count and backfill gaps (`correction_of: null` + a retrospective note).
5. **Commit to git** after logging: `git add data/strength_log.jsonl && git commit -m "Log <date> session"`.

The JSONL is the **single source of truth**. Spreadsheets and the SQLite DB are derived views regenerated from it.

### Never

- Never edit existing lines in `strength_log.jsonl`. Corrections go in a NEW entry with `"correction_of": "<logged_at of bad entry>"`.
- Never write strength data directly to the SQLite DB from chat — that's `scripts/ingest_strength.py`'s job.

## Run tracking (durable, like strength)

Runs come from Strava → the gitignored SQLite DB, so without this they have **no durable in-repo record**.

- After any run analysis, run `python scripts/build_run_log.py`. It regenerates:
  - `data/run_log.jsonl` — **committed, durable** one-line-per-run record (date, distance, pace, HR, zone %, cardiac drift; treadmill runs flagged `pace_reliable: false`).
  - `data/run_log.csv` — gitignored sheet view.
- The script is **idempotent** — rebuilds wholesale from the DB each run; never hand-edit the JSONL.
- **Commit** `data/run_log.jsonl` after each run.
- Treadmill detection: `trainer == true` OR null `start_latlng` in the raw Strava JSON → pace is unreliable; HR/zone data is still trustworthy.

## More durable logs (recovery, sleep, cross-training, bodyweight)

The same discipline extends to everything worth trending — each is a committed JSONL rebuilt from the DB (or a merge that preserves manual entries), so nothing important lives only in the gitignored cache:

- **Recovery** — `python scripts/build_recovery_log.py` → `data/recovery_log.jsonl` (one line/day: sleep score + deep/light/REM/awake totals, resting HR, derived overnight HR floor, HRV, body battery, stress, VO2max, race predictions). Garmin's (unofficial) API is the only source for this, so the committed export is its **only durable backup** — re-run after each sync.
- **Sleep-stage curves** — `python scripts/build_sleep_curves.py` → `data/sleep_curves.jsonl` (one line/night: the full hypnogram). Recovery holds the stage *totals*; this holds the *shape*, which can't be reconstructed once the API is gone. The builder MERGES (never drops an archived night) — just re-run it.
- **Cross-training cardio** — `python scripts/build_cardio_log.py` → `data/cardio_log.jsonl` (non-run aerobic: elliptical/bike/swim, HR zones + drift). Excludes runs, strength and walks. Machine-console readings no API carries (e.g. elliptical watts) go in a per-session `manual` block that survives rebuilds.
- **Bodyweight** — `python scripts/build_weight_log.py` → `data/weight_log.jsonl` (syncs Garmin weigh-ins, preserves manual entries). Load-bearing: it drives protein-per-kg and power-to-weight.

## Visual dashboard

`python scripts/build_dashboard.py` → a single self-contained `dashboard.html` (charts embedded as images; opens offline, no server). Rebuilt from the committed logs; regenerate whenever you want it current.

## Data sources

- Strava activities → `activities` table (`scripts/sync.py`)
- Garmin sleep/HR/stress/body-battery + VO2max, race predictions, HRV status, derived HR floor → `garmin_daily`; intraday streams → `garmin_intraday`
- Garmin per-run running **power + dynamics** (cadence, ground contact, vertical oscillation) → `garmin_activities` (Strava carries none of these; joined onto runs in `build_run_log.py`)
- Strength → `strength_sessions` + `strength_sets` (ingested from the JSONL)
- Durable committed exports: `recovery_log.jsonl`, `sleep_curves.jsonl`, `cardio_log.jsonl`, `weight_log.jsonl`, `run_log.jsonl` (the SQLite DB is a rebuildable cache; these JSONLs are the durable record)

## Training plan

The current plan lives in `TRAINING_PLAN.md`. When the user asks "what's today's session", read it. When they log a session, cross-check against the plan and flag if significantly off.

## Defaults `[EDIT THESE]`

- **Units:** `[kg / lb]`, `[km / mi]`
- **Timezone:** `[e.g. Europe/London]`
- **Polarisation target (running):** `[e.g. ≥75% Z1+Z2, ≤20% Z4+Z5]`

## Data-quality caveats `[EDIT — these are device/individual specific]`

Document gotchas you discover so Claude doesn't relearn them. The list below is hard-won and general — most apply to any Strava + Garmin setup:

- **Treadmill speed from a wrist device is fiction** (accelerometer + post-hoc rescale). Trust HR, not the speed stream. Some machine apps (e.g. Technogym) upload the *same* run to Strava a second time with the real belt distance — `build_run_log.py` dedupes runs starting within 3 min and adopts the machine's distance as the reliable one.
- **Garmin `*TimestampLocal` fields are already shifted to local time.** Read them as-is; do NOT apply the device offset again, or every reported time comes out late by exactly the offset. (Or use `*TimestampGMT` and convert once.) Sanity-check reported wake times against the actual clock before drawing any sleep/circadian conclusion.
- **Body Battery** comes back empty from its dedicated endpoint on many accounts — read it from the intraday `stress` stream under `bodyBatteryValuesArray` (use index `[2]` for the level).
- **Prefer a derived overnight HR floor over Garmin's resting-HR scalar** for recovery trends. The scalar is inflated by a slow-to-settle early night (late meal, alcohol, late bedtime), so it partly measures your *evening*. `garmin_sync` derives `hr_floor` = mean of the lowest ~2% of the sleep-window HR; the gap `resting_hr − hr_floor` is itself a signal.
- **VO2max and race predictions are sparse by design.** Garmin only recomputes VO2max on an outdoor GPS run (never treadmill), so a null day means "no qualifying run", not "no data" — take the most recent non-null value. Race predictions decay when you're not running outdoors, so an upward drift through a treadmill block is an artefact, not fitness loss.
- **Newer Garmin watches** (Forerunner 255+/Vivoactive 5 generation) record overnight HRV + training readiness, but need ~3 weeks of consistent wear before HRV Status appears. **Older watches never record it** — fall back to resting HR, average stress, and body-battery low/high as autonomic proxies.
- **Ergometer watts ≠ running power.** A machine console reports mechanical output; Garmin running power is a *modelled* cost of running — never compare them, or across different (uncalibrated) machines. Watts-at-a-given-HR on the *same* machine over time is a real trend, though.
- **Strava run cadence is per-leg (~76); Garmin's is total steps/min (~152).** Don't mix the units.
- **Sub-1km "runs"** are usually warm-up jogs or accidental recordings — flagged `counts_as_run: false` so they don't inflate run counts / weekly volume, while the row stays in the log.
- **Sport-specific HR zones:** some watches let each activity profile carry HR zones that override the account default. If runs are mis-zoned *on the watch*, check the running profile's own zones first. (Your own analysis derives zones from raw HR, so it's unaffected.)
- **Sleep-latency estimates:** ask for "tried to sleep" time, not "got into bed" time.

## Health & safety

Claude is a coaching *assistant*, not a clinician. It must not diagnose, must defer medical questions to a doctor, and must never act on health metrics without professional input. Record any personal medical constraints (injuries, conditions, medications) here so training advice respects them — `[ADD YOURS]`.
