# Claude Training Companion

Turn [Claude Code](https://claude.com/claude-code) into a personal endurance + strength coach that **pulls your own data**, **tracks every session durably**, and **plans your training** — all from natural-language chat.

It connects to **Strava** (runs/rides) and **Garmin Connect** (sleep, HR, stress, body battery), stores everything in a local SQLite database, and keeps an append-only, git-committed log of every strength session and run so your history is never lost. A bundled Claude Code **skill** runs the same standardised procedure each time you ask, so logging never gets skipped.

> ⚠️ **Not medical advice.** This is a personal-analytics and coaching-assistant template. It does not diagnose or treat anything. Talk to a doctor before changing training, and never act on health numbers without professional input.

---

## What it does

- **Morning recovery check** — pull last night's Garmin HR / stress / body-battery and get a green / amber / red call for the day's training.
- **Strength logging** — tell Claude "I did 5×5 squat at 100 kg" and it appends a structured entry to an append-only JSONL (the single source of truth), rebuilds a per-exercise progression sheet, and commits to git.
- **Run analysis** — pull a run from Strava, compute HR time-in-zone and cardiac drift against a polarisation target, and append it to a durable run log.
- **Training planning** — keep a living `TRAINING_PLAN.md` and have Claude cross-check each session against the plan.

## How it works

```
Strava  ─┐
         ├─► scripts/sync.py ─► data/fitness.db (SQLite, gitignored)
Garmin  ─┘                              │
                                        ├─► build_actuals_sheet.py ─► strength progression view
strength_log.jsonl (committed) ─────────┤
                                        └─► build_run_log.py ─► run_log.jsonl (committed) + CSV
```

The **JSONL files are the source of truth** (committed to git). The SQLite DB and any spreadsheets are *derived views* that can be regenerated at any time.

## Setup

1. **Clone & install**
   ```bash
   git clone https://github.com/jonstraveladventures/claude-training-companion.git
   cd claude-training-companion
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Add your API credentials** — copy `.env.example` to `.env` and fill in:
   - **Strava**: create an app at <https://www.strava.com/settings/api> to get a client ID/secret, then run `python scripts/strava_auth.py` to obtain a refresh token.
   - **Garmin**: your normal Garmin Connect email + password (Garmin has no official API; this uses the community [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) library).

   `.env` is gitignored — your credentials never leave your machine.

3. **Initialise the database & first sync**
   ```bash
   python scripts/init_db.py
   python scripts/sync.py
   ```

4. **Set your personal numbers** (placeholders ship in the repo):
   - HR zones in `scripts/build_run_log.py` (`Z1_MAX … Z4_MAX`). Once you have data, `src/fitness/zones.py` can compute Karvonen/HRR zones for you.
   - Your timezone via the `TZ_NAME` env var (e.g. `export TZ_NAME="Europe/London"`).
   - Edit `CLAUDE.md`, `.claude/skills/training-companion/SKILL.md`, and `TRAINING_PLAN.md` to your goals, constraints, and recovery baselines.

5. **Open the folder in Claude Code** and just talk to it: *"how was my sleep last night?"*, *"I just did 5×5 squats at 100 kg"*, *"pull my run"*, *"weekly review"*. The skill triggers automatically.

## Privacy & safety notes

- All data stays **local** (SQLite + JSONL + your `.env`). Nothing is uploaded anywhere except the API calls to *your own* Strava/Garmin accounts.
- `data/` (the DB, CSVs, images) and `.env` are gitignored by default. **Only the JSONL logs are committed** — review them before pushing to any public remote.
- The Garmin integration uses your account password (no official API exists). Treat your `.env` accordingly and never commit it.
- Built to pair with Claude Code's safety model: it asks before irreversible actions and never enters financial/credential data.

## Layout

| Path | What |
|---|---|
| `src/fitness/` | Strava + Garmin sync, DB schema, HR-zone computation |
| `scripts/` | CLI entry points (sync, logging, sheet/run-log generators, plots) |
| `.claude/skills/training-companion/SKILL.md` | The Claude Code skill (routines: recovery / log / run / weekly review) |
| `CLAUDE.md` | Project conventions + logging protocol Claude follows |
| `TRAINING_PLAN.md` | Your living plan (example provided) |
| `data/` | Local DB + derived views (gitignored) + committed JSONL logs |

## Credits

Built with [Claude Code](https://claude.com/claude-code). Uses [stravalib](https://github.com/stravalib/stravalib) and [python-garminconnect](https://github.com/cyberjunky/python-garminconnect). MIT licensed — see `LICENSE`.
