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

## Data sources

- Strava activities → `activities` table (`scripts/sync.py`)
- Garmin sleep/HR/stress/body-battery → `garmin_daily` + `garmin_intraday` tables
- Strength → `strength_sessions` + `strength_sets` (ingested from the JSONL)

## Training plan

The current plan lives in `TRAINING_PLAN.md`. When the user asks "what's today's session", read it. When they log a session, cross-check against the plan and flag if significantly off.

## Defaults `[EDIT THESE]`

- **Units:** `[kg / lb]`, `[km / mi]`
- **Timezone:** `[e.g. Europe/London]`
- **Polarisation target (running):** `[e.g. ≥75% Z1+Z2, ≤20% Z4+Z5]`

## Data-quality caveats `[EDIT — these are device/individual specific]`

Document gotchas you discover so Claude doesn't relearn them. Common examples:

- **Treadmill speed from a wrist device is often unreliable** (accelerometer + post-hoc rescale). Trust HR, not the speed stream.
- **Older Garmin watches don't record overnight HRV.** Use resting HR, average stress, and body-battery low/high as autonomic proxies instead.
- **Sleep-latency estimates:** ask for "tried to sleep" time, not "got into bed" time.

## Health & safety

Claude is a coaching *assistant*, not a clinician. It must not diagnose, must defer medical questions to a doctor, and must never act on health metrics without professional input. Record any personal medical constraints (injuries, conditions, medications) here so training advice respects them — `[ADD YOURS]`.
