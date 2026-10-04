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
`TRAINING_PLAN.md` at the start if not already in context: they hold the
data-quality caveats, logging schema, units, timezone, and current plan.

**Data stays out of git.** `data/` is gitignored.
Writing a JSONL is the save; there is no commit step for data. Never `git add` anything
under `data/`, and never `git add -f`.

There are five routines. Pick the one matching the request. More than one can run
in a turn (e.g. morning check + log yesterday's session).

> **Personalise the numbers below.** The targets, zone table, and constraints are
> EXAMPLE values: replace them with your own from a test or your data.

---

## Routine 1: Morning recovery check

Trigger: "how was my sleep / last night", "pull my garmin/sleep data", "how was recovery".

1. Pull the data. Sync the daily record FIRST: it holds the HR floor, HRV and HRV Status,
   respiration, sleep stages and readiness this routine reports, and only `garmin_sync`
   writes them. Then pull the intraday streams (the night spans the previous evening to
   this morning, so pull yesterday too if you need the evening half):
   ```
   .venv/bin/python -c "from dotenv import load_dotenv; load_dotenv(); from src.fitness import garmin_sync; print(garmin_sync.sync(days=3))"
   .venv/bin/python -c "from dotenv import load_dotenv; load_dotenv(); from src.fitness.garmin_intraday import pull; print(pull('<today>', streams=['heartrate','stress']))"
   ```
   Rate-limit warnings (429) are common; the data usually still lands.
2. Report these signals against your targets. **Measure body-battery high to actual wake
   time, not a fixed clock cutoff** (the body keeps rebuilding until waking).

   | Signal | Example target | Notes |
   |---|---|---|
   | Sleep score, stages, time awake | your own average | judge REM against your average, not a textbook figure |
   | Overnight HR floor | near your baseline | lead with this, not resting HR |
   | Resting HR | near your baseline | report the gap `resting_hr − hr_floor` |
   | Overnight HRV + HRV Status | inside the status band | see step 3 |
   | Overnight respiration | steady (often ~12/min asleep) | a rise flags illness, alcohol or overreaching |
   | Body-battery high (overnight peak) | > 90 | full consolidation |
   | Body-battery low | > 70 | a low value means you went to bed in recovery debt |
   | Avg overnight stress | < 16 | HRV-derived proxy |
   | Training readiness | your own average | Garmin's composite; newer watches only |

   **Prefer the derived HR floor over Garmin's resting-HR scalar.** The scalar is inflated
   by a slow-to-settle early night (late meal, alcohol, late bedtime), so it partly measures
   the evening. The gap `resting_hr − hr_floor` is itself the signal.
3. **HRV: report the number and the status band, and trust the band.** HRV Status
   (`BALANCED` / `UNBALANCED` / `LOW`) weighs the multi-day trend, so a single high night
   can still read UNBALANCED. Take the band from that night's `hrvSummary.baseline`, show
   the last few nights' statuses, and recompute the running mean from the database every
   time: never quote a baseline written in a file. HRV lags the other markers by a night or
   two, so read it alongside them.
4. **Body battery is embedded in the `stress` stream** (`bodyBatteryValuesArray`, level at
   index 2): read it from there if the dedicated pull errors.
5. **Ask for "tried to sleep" time, not "got into bed"** if estimating latency.
6. Give a clear **green / amber / red** call tied to what's actually scheduled.
7. **Persist it.** The pulled recovery and sleep data lives only in the database cache until
   exported: run `.venv/bin/python scripts/build_recovery_log.py`,
   `.venv/bin/python scripts/build_sleep_curves.py` and
   `.venv/bin/python scripts/build_hrv_trace.py`. Each merges with the file already on disk,
   so a rebuild never blanks older nights. (recovery_log holds the stage totals; sleep_curves
   holds the nightly shape and hrv_trace the overnight HRV readings, neither of which can be
   reconstructed once the API is gone.)

## Routine 2: Log a strength session (MANDATORY full procedure)

Trigger: a workout reported in any form ("I did 5x5 squat at 100", a list, "log this").

**Do this in order: log BEFORE analysing. Skipping is how sessions get lost.**

1. **Append one JSON object** to `data/strength_log.jsonl` (never rewrite; schema in `CLAUDE.md`).
   A correction to an entry gets a new line with `correction_of`. An exercise added to a
   session after the fact is NOT a correction: log it as its own entry without
   `correction_of`, because every reader drops a corrected entry wholesale.
2. **Regenerate views:** `.venv/bin/python scripts/build_actuals_sheet.py` and
   `.venv/bin/python scripts/ingest_strength.py`.
3. **Cross-check vs. the plan** (`TRAINING_PLAN.md`): flag anything off the prescribed
   weight; note any "felt easy" as a signal to recalibrate up.
4. **End the response with the literal line:** `✓ Logged to strength_log.jsonl`.

## Routine 3: Post-run analysis

Trigger: "pull my run", "how was the run", or after a run/treadmill session is mentioned.

1. Sync: `.venv/bin/python scripts/sync.py`.
2. Find today's activity in the `activities` table; backfill streams via
   `src.fitness.strava_detail.backfill(limit=N, include_streams=True)` if missing.
3. **Read what was scheduled for that day before judging anything:**
   `.venv/bin/python -c "from dotenv import load_dotenv; load_dotenv(); from src.fitness import garmin_activities as g; [print(w['title'], *w['steps'], sep='\n  ') for w in g.scheduled('YYYY-MM-DD')]"`
   Judge the run against that workout (an easy run with an HR cap is not a failed interval
   session); if nothing was scheduled, judge it against `TRAINING_PLAN.md`. If the two
   disagree, say so rather than picking one.
4. Compute time-in-zone using your personal zones, plus cardiac-drift quarters (Q1–Q4 mean
   HR). Both are weighted by the time stream: Strava downsamples, so never count samples as
   seconds.
5. **Treadmill speed from the watch is unreliable**: trust HR only, and flag it.
6. Report against your polarisation target.
7. **Track the run:** `.venv/bin/python scripts/build_run_log.py`. It merges with the log
   already on disk, so older runs keep their zones, drift and power after a database rebuild.

## Routine 4: Weekly review

Trigger: "weekly review", or proactively on a chosen day.

Pull from the SQLite DB + the JSONL and report:
1. Run zone distribution for the week vs. target.
2. Strength progression vs. the plan.
3. Recovery drift over the 7 days. Treat next week as a deload if any of these hold: the
   overnight HR floor sits 2 bpm or more above its 14-day mean for 3+ mornings; HRV Status
   reads `UNBALANCED` or `LOW` for 3+ consecutive mornings, or the nightly HRV sits about one
   standard deviation below the recomputed running mean for 2+ mornings; or overnight
   respiration rises and stays up.
4. Recalibration flags: any accessory consistently "easy" gets bumped.
5. Recovery arc: body-battery trend, any amber nights.

## Routine 5: Cross-training, bodyweight & dashboard

- **Cross-training** (elliptical/bike/swim, reported or synced): run
  `.venv/bin/python scripts/build_cardio_log.py`. Log any machine-console reading the APIs
  don't carry (e.g. elliptical watts) into that session's `manual` block: it survives
  rebuilds. Never compare machine watts to running power, or across different
  (uncalibrated) machines.
- **Rowing (Concept2):** if the Concept2 credentials are in `.env`, `scripts/sync.py` pulls
  new Logbook results into `data/concept2_api_cache.json`; otherwise drop a Logbook CSV
  export into `data/concept2_csv/`. Then run `.venv/bin/python scripts/build_rowing_log.py`.
  Use the split-weighted HR, not the headline average, and compare watts across sessions
  only at matching drag factor (see the caveats in `CLAUDE.md`).
- **Bodyweight:** when the user reports a weight, append a manual line to
  `data/weight_log.jsonl` and run `.venv/bin/python scripts/build_weight_log.py` (merges
  Garmin weigh-ins, preserves manual entries). Bodyweight is load-bearing: it drives
  protein-per-kg and power-to-weight.
- **Dashboard:** on request, `.venv/bin/python scripts/build_dashboard.py` renders a
  self-contained `dashboard.html` (gitignored) they can open offline.

---

## Recurring rules `[EDIT THESE]`

- **Constraints:** record injuries/conditions so advice respects them.
- **Main lifts:** leave 2–3 reps in reserve on top sets; don't grind.
- **Never** present unreliable treadmill speed as fact.
- Keep any paste-ready workout formats plain text (no markdown tables).
