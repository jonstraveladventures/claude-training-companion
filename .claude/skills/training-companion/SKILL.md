---
name: training-companion
description: >-
  Personal training routines for this fitness project. Use whenever the user
  asks about sleep/recovery ("how was my sleep", "how was last night", "pull my
  garmin data"), wants to log a strength session ("I did...", "log this
  workout"), wants a run analysed ("pull my run", "how was the run"), or asks
  for a weekly review. Runs the full standardised procedure each time so nothing
  is skipped (especially logging).
---

# Training routines

Always use the project venv (`.venv/bin/python`). Read `CLAUDE.md` and
`TRAINING_PLAN.md` at the start if not already in context — they hold the
data-quality caveats, logging schema, units, timezone, and current plan.

There are five routines. Pick the one matching the request. More than one can run
in a turn (e.g. morning check + log yesterday's session).

> **Personalise the numbers below.** The targets, zone table, and constraints are
> EXAMPLE values — replace them with your own from a test or your data.

---

## Routine 1 — Morning recovery check

Trigger: "how was my sleep / last night", "pull my garmin/sleep data", "how was recovery".

1. Pull the data (the night spans the *previous* evening to *this* morning):
   ```
   .venv/bin/python -c "from dotenv import load_dotenv; load_dotenv(); from src.fitness.garmin_intraday import pull; print(pull('<today>', streams=['heartrate','stress']))"
   ```
   Rate-limit warnings (429) are common — the data usually still lands.
2. Compute and report these signals against your targets. **Measure body-battery
   high to actual wake time, not a fixed clock cutoff** (the body keeps rebuilding
   until waking).

   | Signal | Example target | Notes |
   |---|---|---|
   | Body-battery high (overnight peak) | > 90 | full consolidation |
   | Body-battery low | > 70 | low value = went to bed in recovery debt |
   | Avg overnight stress | < 16 | HRV-derived proxy |
   | Resting HR | near your baseline | most reliable single signal |
   | Overnight HR floor | near your baseline | from intraday HR stream |

   **Prefer the derived HR floor over Garmin's resting-HR scalar** — the scalar is
   inflated by a slow-to-settle early night, so it partly measures the *evening*.
   The gap `resting_hr − hr_floor` is itself the signal (how elevated the early
   night stayed).

3. **Body battery is embedded in the `stress` stream** (`bodyBatteryValuesArray`,
   level at index 2) — read it from there if the dedicated pull errors.
4. **Ask for "tried to sleep" time, not "got into bed"** if estimating latency.
5. Give a clear **green / amber / red** call tied to what's actually scheduled.
6. **Persist it (durable, like strength/runs).** The pulled recovery + sleep data
   lives only in the gitignored DB until exported — run
   `.venv/bin/python scripts/build_recovery_log.py` and
   `.venv/bin/python scripts/build_sleep_curves.py`, then
   `git add data/recovery_log.jsonl data/sleep_curves.jsonl && git commit -m "Recovery <date>"`.
   (recovery_log holds the stage *totals*; sleep_curves holds the nightly *shape*,
   which can't be reconstructed once the API is gone.)

## Routine 2 — Log a strength session (MANDATORY full procedure)

Trigger: a workout reported in any form ("I did 5x5 squat at 100", a list, "log this").

**Do this in order — log BEFORE analysing. Skipping = sessions get lost.**

1. **Append one JSON object** to `data/strength_log.jsonl` (never rewrite; schema in `CLAUDE.md`).
2. **Regenerate views:** `.venv/bin/python scripts/build_actuals_sheet.py`.
3. **Commit:** `git add data/strength_log.jsonl && git commit -m "Log <date> session"`.
4. **Cross-check vs. the plan** (`TRAINING_PLAN.md`) — flag if off prescribed weight;
   note any "felt easy" → recalibrate-up signals.
5. **End the response with the literal line:** `✓ Logged to strength_log.jsonl`.

## Routine 3 — Post-run analysis

Trigger: "pull my run", "how was the run", or after a run/treadmill session is mentioned.

1. Sync: `.venv/bin/python scripts/sync.py`.
2. Find today's activity in the `activities` table; backfill streams via
   `src.fitness.strava_detail.backfill(limit=N, include_streams=True)` if missing.
3. Compute time-in-zone using your personal zones, plus cardiac-drift quarters (Q1–Q4 mean HR).
4. **Treadmill speed from the watch is unreliable** — trust HR only; flag it.
5. Report against your polarisation target.
6. **Track the run:** run `.venv/bin/python scripts/build_run_log.py`, then
   `git add data/run_log.jsonl && git commit -m "Run log <date>"`.

## Routine 4 — Weekly review

Trigger: "weekly review", or proactively on a chosen day.

Pull from the SQLite DB + the JSONL and report:
1. Run zone distribution for the week vs. target.
2. Strength progression vs. the plan.
3. Resting-HR / overnight-stress drift over 7 days (flag a sustained rise → consider a deload).
4. Recalibration flags — any accessory consistently "easy" → bump.
5. Recovery arc — body-battery trend, any amber nights.

## Routine 5 — Cross-training, bodyweight & dashboard

- **Cross-training** (elliptical/bike/swim, reported or synced): run
  `.venv/bin/python scripts/build_cardio_log.py` and commit `data/cardio_log.jsonl`.
  Log any machine-console reading the APIs don't carry (e.g. elliptical watts) into
  that session's `manual` block — it survives rebuilds. Never compare machine watts
  to running power, or across different (uncalibrated) machines.
- **Bodyweight:** when the user reports a weight, append a manual line to
  `data/weight_log.jsonl`, run `.venv/bin/python scripts/build_weight_log.py`
  (merges Garmin weigh-ins, preserves manual entries), and commit. Bodyweight is
  load-bearing — it drives protein-per-kg and power-to-weight.
- **Dashboard:** on request, `.venv/bin/python scripts/build_dashboard.py` renders a
  self-contained `dashboard.html` (gitignored) they can open offline.

---

## Recurring rules `[EDIT THESE]`

- **Constraints:** record injuries/conditions so advice respects them.
- **Main lifts:** leave 2–3 reps in reserve on top sets; don't grind.
- **Never** present unreliable treadmill speed as fact.
- Keep any paste-ready workout formats plain text (no markdown tables).
