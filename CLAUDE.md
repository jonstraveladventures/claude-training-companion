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
5. **Commit to git** after logging: `git add data/strength_log.jsonl && git commit -m "Log <date> session"`. (If you keep `data/` out of git altogether, as the README's privacy section describes, the append itself is the save: skip this step and never `git add` anything under `data/`.)

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
- **Overnight HRV trace:** `python scripts/build_hrv_trace.py` → `data/hrv_trace.jsonl` (one line/night: the ~90 five-minute HRV readings across the night, plus the nightly and weekly averages and Garmin's status). Recovery holds the nightly *average*; this shows *when* recovery happened: a suppressed early night after an evening session that rebounds before waking reads very differently from the average alone. Watches that record HRV only; MERGES like the sleep curves.
- **Cross-training cardio** — `python scripts/build_cardio_log.py` → `data/cardio_log.jsonl` (non-run aerobic: elliptical/bike/swim, HR zones + drift). Excludes runs, strength and walks. Machine-console readings no API carries (e.g. elliptical watts) go in a per-session `manual` block that survives rebuilds.
- **Bodyweight** — `python scripts/build_weight_log.py` → `data/weight_log.jsonl` (syncs Garmin weigh-ins, preserves manual entries). Load-bearing: it drives protein-per-kg and power-to-weight.
- **Rowing (Concept2):** `python scripts/build_rowing_log.py` → `data/rowing_log.jsonl` from Logbook CSV exports dropped in `data/concept2_csv/` (one line/workout, pace per 500 m, HR 0 → null). The dashboard stacks it onto the cross-training chart when the file exists.
- `scripts/backfill_garmin_columns.py` re-derives the structured `garmin_daily` columns (respiration, weekly HRV baseline, light/awake sleep) from the stored `raw_json` with no API call. Run it after a schema change, then rebuild the recovery log.

## Visual dashboard

`python scripts/build_dashboard.py` → a single self-contained `dashboard.html` (charts embedded as images; opens offline, no server). Rebuilt from the committed logs; regenerate whenever you want it current. Weekly charts are indexed by calendar week, so a week with nothing logged shows as a gap rather than being skipped. Exercise names are canonicalised through `src/fitness/exercise_names.py`, one alias table shared with the progression sheet: when a variant spelling appears in the log ("face pull" beside "face pulls"), add a line there rather than editing the JSONL.

## Data sources

- Strava activities → `activities` table (`scripts/sync.py`)
- Garmin sleep/HR/stress/body-battery + VO2max, race predictions, HRV status, derived HR floor → `garmin_daily`; intraday streams → `garmin_intraday`
- Garmin per-run running **power + dynamics** (cadence, ground contact, vertical oscillation) → `garmin_activities` (Strava carries none of these; joined onto runs in `build_run_log.py`)
- Strength → `strength_sessions` + `strength_sets` (ingested from the JSONL)
- Durable committed exports: `recovery_log.jsonl`, `sleep_curves.jsonl`, `hrv_trace.jsonl`, `cardio_log.jsonl`, `weight_log.jsonl`, `run_log.jsonl`, `rowing_log.jsonl` (the SQLite DB is a rebuildable cache; these JSONLs are the durable record)
- Credentials live in `.env` (mode 600). Strava may rotate the refresh token on use; `strava_sync` writes the new one back to `.env` itself, atomically, so never hand-edit `.env` while a sync is running.

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
- **HRV Status weighs the multi-day trend, not the single night.** Once the baseline exists, `hrvSummary.status` (`BALANCED` / `UNBALANCED` / `LOW`) and the `baseline` band can disagree with the raw nightly figure: a week's highest reading was classified `UNBALANCED`, and a lower one two nights later `BALANCED`. Report the band beside the number and trust the band; never call a night good because the milliseconds rose. HRV also lags the other markers by a night or two, so read it alongside resting HR and body battery, not instead of them. And judge the nightly figure against a running mean recomputed from the data every time, never against a number written in this file: a baseline quoted in a file like this one went 3 ms stale within a month.
- **Ergometer watts ≠ running power.** A machine console reports mechanical output; Garmin running power is a *modelled* cost of running — never compare them, or across different (uncalibrated) machines. Watts-at-a-given-HR on the *same* machine over time is a real trend, though.
- **Strava run cadence is per-leg (~76); Garmin's is total steps/min (~152).** Don't mix the units.
- **Sub-1km "runs"** are usually warm-up jogs or accidental recordings — flagged `counts_as_run: false` so they don't inflate run counts / weekly volume, while the row stays in the log.
- **Sport-specific HR zones:** some watches let each activity profile carry HR zones that override the account default. If runs are mis-zoned *on the watch*, check the running profile's own zones first. (Your own analysis derives zones from raw HR, so it's unaffected.)
- **Sleep-latency estimates:** ask for "tried to sleep" time, not "got into bed" time.
- **Strava activity streams are DOWNSAMPLED — never count samples as seconds.** Streams come back at variable resolution, not 1 Hz: a 2384 s run returned 1000 samples at mostly 2 s intervals. So `sum(1 for v in hr if v >= X)` gives *samples*, not seconds, and undercounts time-in-zone by roughly the sampling factor — it reported 8:17 above a threshold where the truth was **16:03**, exactly half. Always weight by the time stream: `sum(t[i]-t[i-1] for i in range(1,len(t)) if hr[i] and hr[i] >= X)`. Cross-check any ad-hoc duration against the zone percentages, which are computed correctly — if `pct x elapsed` and your figure disagree, your figure is wrong.
- **Watch-recorded strength data is unreliable on THREE independent axes.** `get_activity_exercise_sets()` is the only per-set record of a lift, and every part of it can be wrong. (1) **Weights are fiction on bodyweight work** — the watch requires a number for every set, so bodyweight exercises acquire a fabricated load that is really the lifter's own estimate, and may differ day to day for the same movement. Log `weight_kg: null` and keep the number in a separate `watch_entered_kg` field if you want the provenance; never read it as a progression. (2) **Exercise labels are auto-guessed** — records carry a category and a confidence, and real lifts come back as `SHRUG` or `LUNGE` at 40-55%, or `UNKNOWN` at 99%. Map by load + rep pattern + the session plan instead. (3) **Sets go missing, and phantom sets appear** — a 5-rep squat logged in 4 s, or ten reps in 8 s, is usually one set split across two records; a huge rep count with a near-zero duration is a manual after-the-fact entry. Units: `weight` is in **grams**; filter to `setType == "ACTIVE"`. **Consequence: always show the parsed numbers to the athlete and let them correct what the exercise was, how many sets, and whether the weight is real, before treating any of it as the record.**
- **`restlessMomentsCount` is blind to movement while awake.** It counts micro-movements during *detected sleep* only, so once the watch scores a period as Awake, conscious tossing and turning in that window does not raise the number. Across 9 nights it correlated with awake-minutes at only r = +0.31, and the extremes inverted. **A normal restless count never rules out a night the athlete describes as broken** — believe the subjective report over the metric here.
- **Interval-run recordings often stop at the last hard rep, and HR lag hides the recovery length.** Athletes commonly stop the timer when they head home, so a missing easy tail is not evidence the cool-down was skipped — ask. And don't estimate recovery duration from the width of the HR trough between reps: HR takes 30-45 s to fall after a rep and rises again before the next one starts, so a true 3:00 recovery can look like 2:30. Map reps onto the prescribed grid instead.
- **Concept2 Logbook (if you row):** the API's headline `heart_rate.average` runs up to ~9 bpm high, with `min`/`max` often 0; compute the time-weighted mean of the splits' HR instead, and drop split 1 when judging drift (it starts from rest). The logged `drag_factor` is not a reading of the damper: with the damper untouched it has moved 20–35% between sessions, and the monitor's watts and pace scale with it, so compare erg watts or pace across sessions only at matching drag, and otherwise compare HR. Neither the API nor Strava carries the per-stroke force curve; [pm5-force-logger](https://github.com/jonstraveladventures/pm5-force-logger) records it over Bluetooth.
- **Exercise-name drift.** Names logged from chat drift over months ("RDL", "face pull", "face pulls"), and every view groups by name. `src/fitness/exercise_names.py` maps variants to one canonical name for all of them; add a line there, never edit the JSONL.

## Analysis discipline (read before making any claim about the data)

These are failure modes an LLM working over a training log falls into repeatedly. They produced
real wrong answers here before being written down.

**Superlative claims — longest / heaviest / fastest / PR / "first time".** Before asserting any:

1. **The query window must match the claimed window.** If a script prints several blocks with different date filters, never carry a result from a narrow block into a sentence about a wide one. (A "longest run in six weeks" claim was once computed from a 12-day filter.)
2. **Cross-check against aggregates already on screen.** A maximum must be greater than or equal to the mean of the same set. `total / count` is one line of arithmetic and catches this instantly.
3. **Check the boundary.** Re-run a "last 6 weeks" claim at 7 and 8 weeks. Big efforts cluster just outside arbitrary cut-offs, and a claim that flips when the boundary moves by a day was never real.
4. **Trust the athlete's memory as a signal.** They have years of context your query window excludes. "I thought I did something longer" is evidence to re-run the query wider, not something to defend the first answer against.

**Never characterise a number without its distribution.** "77 minutes a week, that's thin" was wrong: two thirds of that year's weeks were below it. Compute the mean, the spread and the athlete's own range before attaching an adjective.

**Watch for hidden zero periods and mixed units when averaging.** Averaging six weeks that include a two-week travel gap describes neither the training nor the gap. And treadmill distance is unreliable, so a weekly total mixing treadmill and outdoor kilometres is part fiction — **track treadmill weeks by time, not distance.**

**Don't compare across a device change.** Sleep-stage figures in particular are not comparable between watch generations — one device averaged 37 min of deep sleep a night where its replacement averaged 77 for the same person. An all-time median across a device switch is meaningless. Split the comparison at the changeover date.

**Compute, don't eyeball.** Reading a number off rounded output produces confident errors — a displayed "90.0" that is really 89.97 breaks a `>= 90` streak you just claimed.

## Health & safety

Claude is a coaching *assistant*, not a clinician. It must not diagnose, must defer medical questions to a doctor, and must never act on health metrics without professional input. Record any personal medical constraints (injuries, conditions, medications) here so training advice respects them — `[ADD YOURS]`.
