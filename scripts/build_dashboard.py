"""Build a single self-contained, offline dashboard.html from the durable logs.

Reads data/strength_log.jsonl, data/run_log.jsonl, data/recovery_log.jsonl and
TRAINING_PLAN.md, renders every chart with matplotlib, and embeds them as
base64 PNGs inside one HTML file with inlined CSS — no network access needed
to view it. Idempotent: rebuilds wholesale from the source data every run.

Run: .venv/bin/python scripts/build_dashboard.py
Output: dashboard.html at the repo root (gitignored — regenerate, don't edit).
"""
import base64
import io
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "dashboard.html"
sys.path.insert(0, str(ROOT / "src"))
from fitness.exercise_names import canon  # noqa: E402  (same alias table as the sheet view)

# ---------------------------------------------------------------------------
# Palette (validated categorical set, dataviz skill reference palette).
# Charts stay light-mode regardless of page theme, per spec.
# ---------------------------------------------------------------------------
CAT = {
    "blue": "#2a78d6", "aqua": "#1baf7a", "yellow": "#eda100", "green": "#008300",
    "violet": "#4a3aa7", "red": "#e34948", "magenta": "#e87ba4", "orange": "#eb6834",
}
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"
BASELINE = "#c3c2b7"
GOOD = "#0ca30c"

# >>> SET YOUR OWN <<< the lifts that get a progression panel (canonical names, as logged)
KEY_LIFTS = [
    "back squat", "low-incline DB bench", "overhead press",
    "lat pulldown", "romanian deadlift", "seated dumbbell shoulder press",
]


def set_style():
    plt.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "axes.edgecolor": BASELINE,
        "axes.labelcolor": INK_SECONDARY,
        "axes.titlecolor": INK,
        "text.color": INK,
        "xtick.color": INK_MUTED,
        "ytick.color": INK_MUTED,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica Neue", "Arial", "DejaVu Sans"],
        "font.size": 10.5,
        "axes.titlesize": 11.5,
        "axes.titleweight": "bold",
        "figure.dpi": 150,
        "legend.frameon": False,
    })


def fig_to_b64(fig, tight=True):
    buf = io.BytesIO()
    if tight:
        fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.15)
    else:
        fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def img_tag(fig, alt="", tight=True):
    b64 = fig_to_b64(fig, tight=tight)
    return f'<img class="chart" src="data:image/png;base64,{b64}" alt="{alt}">'


def no_data_note(msg="No data yet."):
    return f'<div class="no-data">{msg}</div>'


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_jsonl(path):
    if not path.exists():
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"WARN {path}: skipped malformed line: {e}", file=sys.stderr)
    return out


def load_strength():
    """Load strength sessions, honouring corrections (drop superseded entries)."""
    raw = load_jsonl(DATA / "strength_log.jsonl")
    superseded = {r["correction_of"] for r in raw if r.get("correction_of")}
    sessions = [r for r in raw if r.get("logged_at") not in superseded]
    sessions.sort(key=lambda r: r.get("session_date") or r.get("logged_at") or "")
    return sessions


def top_set(sets):
    """The best logged set: heaviest weight, then most reps, then longest hold.
    Ties (same weight, multiple sets — the norm in double progression) break
    on the highest reps, so the reported set reflects the best performance at
    that load rather than just the first set logged. Bodyweight and isometric
    sets (weight_kg null) count too; they used to be discarded, which made a
    plank, a dragon flag or a tendon hold vanish from the session table."""
    candidates = [s for s in sets if isinstance(s, dict)
                  and (s.get("weight_kg") is not None or s.get("reps") or s.get("hold_s"))]
    if not candidates:
        return None
    return max(candidates, key=lambda s: (s["weight_kg"] if s.get("weight_kg") is not None else -1,
                                          s.get("reps") or 0, s.get("hold_s") or 0))


MAINT_RE = re.compile(r"\b(maintenance|deload|de-load)\b", re.I)


def is_maintenance(session, ex):
    """True if a set is deliberately light (travel maintenance / deload) and so
    should NOT count as a working top set or drive the progression trend. Set
    stays in the log; it's just excluded from 'current level' displays.
    Honours an explicit `maintenance: true` flag (exercise or session), and
    falls back to keyword detection in the session label / exercise notes."""
    if ex.get("maintenance") or session.get("maintenance"):
        return True
    text = f"{session.get('session_label') or ''} {ex.get('notes') or ''}"
    return bool(MAINT_RE.search(text))


def top_set_detail(sets):
    """(weight, reps, hold_s, n_working_sets_at_top_weight) for the top set."""
    ts = top_set(sets)
    if not ts:
        return None
    w = ts.get("weight_kg")
    n = sum(1 for s in sets if isinstance(s, dict) and s.get("weight_kg") == w)
    return w, ts.get("reps"), ts.get("hold_s"), n


def fmt_top_set(sets):
    """Compact 'Wkg N×reps' for the top working set — N×reps makes the double
    progression legible (5×6 vs 5×8). Bodyweight shows as 'BW'; holds in seconds."""
    d = top_set_detail(sets)
    if not d:
        return None
    w, reps, hold, n = d
    label = f"{w:g}kg" if w is not None else "BW"
    if reps:
        return f"{label} {n}&times;{reps}" if n > 1 else f"{label}&times;{reps}"
    if hold:
        return f"{label} {n}&times;{hold}s" if n > 1 else f"{label}&times;{hold}s"
    return label


def load_runs():
    return load_jsonl(DATA / "run_log.jsonl")


def load_recovery():
    recs = load_jsonl(DATA / "recovery_log.jsonl")
    recs.sort(key=lambda r: r["date"])
    return recs


def load_cardio():
    return load_jsonl(DATA / "cardio_log.jsonl")


def load_rowing():
    return load_jsonl(DATA / "rowing_log.jsonl")


PROTEIN_LO, PROTEIN_HI = 1.8, 2.2   # g/kg/day — >>> SET YOUR OWN <<< (1.6–2.2 is the usual range)


def load_weight():
    rows = load_jsonl(DATA / "weight_log.jsonl")
    rows.sort(key=lambda r: r["date"])
    return rows


def build_weight_trend(weight):
    if len(weight) < 2:
        return no_data_note("Not enough weigh-ins yet.")
    dates_ = [parse_date(r["date"]) for r in weight]
    kg = [r["weight_kg"] for r in weight]
    fig, ax = plt.subplots(figsize=(9.5, 3.4))
    ax.plot(dates_, kg, marker="o", markersize=4, linewidth=2, color=CAT["blue"])
    ax.annotate(f"{kg[-1]:g} kg", (dates_[-1], kg[-1]), textcoords="offset points",
                xytext=(0, 8), ha="center", fontsize=9, color=CAT["blue"])
    ax.set_ylabel("kg")
    ax.set_title("Bodyweight")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.tick_params(axis="x", rotation=30, labelsize=8)
    fig.tight_layout()
    note = (f'<p style="font-size:0.82rem;color:#888;margin:0.3rem 0 0;">'
            f'Protein target scales with this: <b>{kg[-1] * PROTEIN_LO:.0f}–{kg[-1] * PROTEIN_HI:.0f} g/day</b> '
            f'({PROTEIN_LO}–{PROTEIN_HI} g/kg). Running power is W/kg, so it moves too.</p>')
    return img_tag(fig, alt="Bodyweight over time") + "\n" + note


# ---------------------------------------------------------------------------
# TRAINING_PLAN.md section extraction + tiny markdown -> HTML renderer
# ---------------------------------------------------------------------------

def extract_section(md_text, heading):
    lines = md_text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == heading:
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    block = lines[start:end]
    # trim leading/trailing blank lines and stray horizontal rules
    while block and (not block[0].strip() or block[0].strip() == "---"):
        block.pop(0)
    while block and (not block[-1].strip() or block[-1].strip() == "---"):
        block.pop()
    return "\n".join(block)


def inline_md(text):
    text = esc(text)   # the plan is prose, so a literal < or & must not become markup
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*(?!\*)", r"<i>\1</i>", text)
    return text


def md_table(block_lines):
    """A markdown pipe table as a plain HTML table (header row, then body rows)."""
    rows = []
    for ln in block_lines:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue   # the |---|---| separator line
        rows.append(cells)
    if not rows:
        return ""
    head = "".join(f"<th>{inline_md(c)}</th>" for c in rows[0])
    body = "".join("<tr>" + "".join(f"<td>{inline_md(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
    return f'<table class="sessions"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def md_to_html(md_text):
    if not md_text:
        return no_data_note("Plan section not found.")
    blocks = re.split(r"\n\s*\n", md_text.strip())
    html = []
    for block in blocks:
        block_lines = [ln for ln in block.splitlines() if ln.strip()]
        if not block_lines:
            continue
        if all(ln.strip().startswith("- ") for ln in block_lines):
            html.append("<ul>")
            for ln in block_lines:
                html.append(f"<li>{inline_md(ln.strip()[2:])}</li>")
            html.append("</ul>")
        elif block_lines[0].strip().startswith("|"):
            html.append(md_table(block_lines))
        else:
            html.append(f"<p>{inline_md(' '.join(ln.strip() for ln in block_lines))}</p>")
    return "\n".join(html)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_mmss(seconds):
    if seconds is None:
        return None
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def week_start(d):
    return d - timedelta(days=d.weekday())  # Monday


def last_calendar_weeks(weeks, end=None):
    """The Mondays of the last `weeks` calendar weeks, ending with the current one.
    Charts index by these so a week with nothing logged shows as a gap at zero;
    taking "the last N weeks that have data" hid every zero week and made a
    16-week chart quietly span 19."""
    end = week_start(end or date.today())
    return [end - timedelta(days=7 * k) for k in reversed(range(weeks))]


def esc(s):
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def build_snapshot_cards(sessions, runs, recovery, weight):
    cards = []

    # Latest WORKING squat top set (maintenance/travel/deload sessions excluded)
    squat_entries = []
    for s in sessions:
        for ex in s["exercises"]:
            if canon(ex["name"]) == "back squat" and not is_maintenance(s, ex):
                if top_set(ex["sets"]):
                    squat_entries.append((s["session_date"], ex["sets"]))
    if squat_entries:
        d, sets = squat_entries[-1]
        cards.append(("Latest working squat", fmt_top_set(sets), d))
    else:
        cards.append(("Latest working squat", "—", "no working set"))

    # Bodyweight + the protein target it drives
    if weight:
        w = weight[-1]
        cards.append(("Bodyweight", f'{w["weight_kg"]:g} kg', w["date"]))
        cards.append(("Protein target",
                      f'{w["weight_kg"] * PROTEIN_LO:.0f}–{w["weight_kg"] * PROTEIN_HI:.0f} g',
                      f'{PROTEIN_LO}–{PROTEIN_HI} g/kg'))

    # This-week running km (counts_as_run)
    today = date.today()
    ws = week_start(today)
    week_km = sum(
        r["distance_km"] for r in runs
        if r.get("counts_as_run") and r.get("distance_km")
        and parse_date(r["date"]) >= ws
    )
    if runs:   # an empty run log is "no data", not a 0.0 km week
        cards.append(("This week's running", f"{week_km:.1f} km", f"since {ws.isoformat()}"))
    else:
        cards.append(("This week's running", "—", "no runs logged"))

    # Latest resting HR / HR floor / HRV / VO2max / race 5k, from recovery_log (most recent non-null)
    def latest_val(key):
        for r in reversed(recovery):
            if r.get(key) is not None:
                return r[key], r["date"]
        return None, None

    rhr, rhr_d = latest_val("resting_hr")
    cards.append(("Latest resting HR", f"{rhr:g} bpm" if rhr is not None else "—", rhr_d or "no data"))

    # The derived overnight floor is the recovery number to lead with; Garmin's resting-HR
    # scalar is inflated by a slow-to-settle early night, and the gap between them is itself
    # the signal (CLAUDE.md, Data sources).
    fl, fl_d = latest_val("hr_floor")
    if fl is not None:
        same_day = next((r for r in recovery if r["date"] == fl_d), {})
        gap = same_day.get("resting_hr")
        sub = f"{fl_d}, resting HR {gap - fl:+g} above it" if gap is not None else fl_d
        cards.append(("Latest HR floor", f"{fl:g} bpm", sub))
    else:
        cards.append(("Latest HR floor", "—", "no data"))

    hrv, hrv_d = latest_val("hrv_overnight")
    cards.append(("Latest overnight HRV", f"{hrv:g} ms" if hrv is not None else "—", hrv_d or "no data (needs a watch that records HRV)"))

    vo2, vo2_d = latest_val("vo2max")
    cards.append(("Latest VO2max", f"{vo2:g}" if vo2 is not None else "—", vo2_d or "no data"))

    r5k, r5k_d = latest_val("race_5k_s")
    cards.append(("5k race prediction", fmt_mmss(r5k) if r5k is not None else "—", r5k_d or "no data"))

    html = ['<div class="cards">']
    for title, value, sub in cards:
        html.append(
            f'<div class="card"><div class="card-title">{esc(title)}</div>'
            f'<div class="card-value">{value}</div>'
            f'<div class="card-sub">{esc(sub)}</div></div>'
        )
    html.append("</div>")
    return "\n".join(html)


def lift_series(sessions, lift_name):
    """(date, weight, reps, e1rm, maintenance) for a lift's top set per session."""
    out = []
    for s in sessions:
        for ex in s["exercises"]:
            if canon(ex["name"]) == lift_name:
                ts = top_set(ex["sets"])
                if ts and ts.get("weight_kg") is not None:   # the charts plot load, so bodyweight sets stay out
                    w = ts["weight_kg"]
                    reps = ts.get("reps")
                    e1rm = w * (1 + reps / 30) if reps else None
                    out.append((parse_date(s["session_date"]), w, reps, e1rm,
                                is_maintenance(s, ex)))
    return out


def build_strength_progression(sessions):
    present = [lift for lift in KEY_LIFTS if lift_series(sessions, lift)]
    if not present:
        return no_data_note("No strength sessions logged yet.")

    n = len(present)
    ncols = 3
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(4.4 * ncols, 3.2 * nrows), squeeze=False)
    for i, lift in enumerate(present):
        ax = axes[i // ncols][i % ncols]
        series = lift_series(sessions, lift)
        # Line + filled markers = working sets (drive the trend); hollow grey
        # markers = maintenance/deload/travel (kept visible, but off the trend).
        wk = [p for p in series if not p[4]]
        mt = [p for p in series if p[4]]
        if wk:
            ax.plot([p[0] for p in wk], [p[1] for p in wk],
                    marker="o", markersize=4, linewidth=2, color=CAT["blue"])
            # Annotate reps at each working set so a fixed-weight rep climb
            # (double progression: 90×5 → 90×6 → 90×7) reads as progress, not a
            # flat line. Label the last point always; earlier ones when reps change.
            prev = None
            for j, p in enumerate(wk):
                r = p[2]
                if r and (j == len(wk) - 1 or r != prev):
                    ax.annotate(f"×{r}", (p[0], p[1]), textcoords="offset points",
                                xytext=(0, 6), ha="center", fontsize=7.5, color="#5a5a5a")
                prev = r
        if mt:
            ax.scatter([p[0] for p in mt], [p[1] for p in mt], s=28,
                       facecolors="none", edgecolors="#a0a0a0", linewidths=1.2, zorder=3)
        ax.set_title(lift, fontsize=10.5)
        ax.set_ylabel("kg", fontsize=9)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.tick_params(axis="x", rotation=30, labelsize=8)
        ax.tick_params(axis="y", labelsize=8)
    # hide unused axes
    for j in range(n, nrows * ncols):
        axes[j // ncols][j % ncols].axis("off")
    fig.tight_layout()
    grid_html = img_tag(fig, alt="Top-set weight over time for key lifts")

    # Back squat detail panel: weight + reps-at-top-weight, plus e1RM.
    # Working sets drive the trend/e1RM; maintenance shown hollow/grey, uncounted.
    squat_series = lift_series(sessions, "back squat")
    squat_html = no_data_note("No back squat sessions logged yet.")
    if squat_series:
        wk = [p for p in squat_series if not p[4]]
        mt = [p for p in squat_series if p[4]]
        fig2, (ax1, ax2) = plt.subplots(2, 1, figsize=(9.5, 5.6), sharex=True,
                                         gridspec_kw={"height_ratios": [2, 1]})
        if wk:
            ax1.plot([p[0] for p in wk], [p[1] for p in wk], marker="o", markersize=4,
                     linewidth=2, color=CAT["blue"], label="Working top-set weight")
            e1 = [(p[0], p[3]) for p in wk if p[3] is not None]
            if e1:
                ax1.plot([d for d, _ in e1], [e for _, e in e1], marker="s", markersize=3,
                          linewidth=1.4, linestyle="--", color=CAT["aqua"],
                          label="Est. e1RM (Epley)")
        if mt:
            ax1.scatter([p[0] for p in mt], [p[1] for p in mt], s=32, facecolors="none",
                        edgecolors="#a0a0a0", linewidths=1.3, zorder=3,
                        label="Maintenance / deload (not counted)")
        ax1.set_ylabel("kg")
        ax1.set_title("Back squat — top-set weight & estimated e1RM")
        ax1.legend(loc="upper left", fontsize=8.5)

        ax2.bar([p[0] for p in wk], [p[2] or 0 for p in wk], width=3.5, color=CAT["orange"])
        if mt:
            ax2.bar([p[0] for p in mt], [p[2] or 0 for p in mt], width=3.5, color="#c8c8c8")
        ax2.set_ylabel("reps")
        ax2.set_title("Reps at top-set weight (double progression)", fontsize=10.5)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax2.tick_params(axis="x", rotation=30, labelsize=8)
        fig2.tight_layout()
        squat_html = img_tag(fig2, alt="Back squat weight and reps progression")

    note = ('<p style="font-size:0.82rem;color:#888;margin:0.3rem 0 0.6rem;">'
            'Hollow grey markers = maintenance / deload / travel sessions — kept in the log '
            'but excluded from the working-set trend and the “latest working squat” figure.</p>')
    return grid_html + "\n" + note + "\n" + squat_html


def build_recent_sessions_table(sessions):
    if not sessions:
        return no_data_note("No strength sessions logged yet.")
    recent = list(reversed(sessions))[:12]
    rows = []
    for s in recent:
        parts = []
        for ex in s["exercises"]:
            detail = fmt_top_set(ex["sets"])
            if not detail:
                continue
            parts.append(f"{esc(canon(ex['name']))} {detail}")
        rows.append((s["session_date"], s.get("session_label", ""), "; ".join(parts)))

    html = ['<table class="sessions"><thead><tr><th>Date</th><th>Session</th><th>Top sets</th></tr></thead><tbody>']
    for d, label, summary in rows:
        html.append(f"<tr><td class='nowrap'>{esc(d)}</td><td>{esc(label)}</td><td class='summary'>{summary}</td></tr>")
    html.append("</tbody></table>")
    return "\n".join(html)


def weekly_run_totals(runs, weeks=16):
    by_week = defaultdict(float)
    for r in runs:
        if not r.get("counts_as_run") or not r.get("distance_km"):
            continue
        d = parse_date(r["date"])
        by_week[week_start(d)] += r["distance_km"]
    if not by_week:
        return []
    return [(w, by_week.get(w, 0.0)) for w in last_calendar_weeks(weeks)]


def build_running_volume(runs):
    weekly = weekly_run_totals(runs, weeks=16)
    if not weekly:
        return no_data_note("No runs logged yet.")
    fig, ax = plt.subplots(figsize=(10, 3.6))
    xs = [w for w, _ in weekly]
    ys = [km for _, km in weekly]
    ax.bar(xs, ys, width=5.0, color=CAT["blue"])
    ax.set_ylabel("km")
    ax.set_title(f"Weekly running volume — last {len(weekly)} calendar weeks (counts_as_run; a missing bar is a zero week)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.tick_params(axis="x", rotation=30, labelsize=8.5)
    for x, y in zip(xs, ys):
        if y > 0:
            ax.annotate(f"{y:.0f}", (x, y), textcoords="offset points", xytext=(0, 3),
                        ha="center", fontsize=7.5, color=INK_SECONDARY)
    fig.tight_layout()
    return img_tag(fig, alt="Weekly running volume")


def build_polarisation(runs):
    by_week = defaultdict(lambda: {"z12": 0.0, "z3": 0.0, "z45": 0.0, "tot": 0.0})
    for r in runs:
        if not r.get("counts_as_run"):
            continue
        zp = r.get("zones_pct")
        t = r.get("moving_time_s")
        if not zp or not t:
            continue
        d = parse_date(r["date"])
        wk = by_week[week_start(d)]
        z12_pct = (zp.get("Z1", 0) + zp.get("Z2", 0)) / 100
        z3_pct = zp.get("Z3", 0) / 100
        z45_pct = (zp.get("Z4", 0) + zp.get("Z5", 0)) / 100
        wk["z12"] += z12_pct * t
        wk["z3"] += z3_pct * t
        wk["z45"] += z45_pct * t
        wk["tot"] += t

    if not by_week:
        return no_data_note("No runs with HR-zone data yet.")

    xs = last_calendar_weeks(16)
    share = lambda w, k: 100 * by_week[w][k] / by_week[w]["tot"] if by_week.get(w, {}).get("tot") else 0.0
    z12 = [share(w, "z12") for w in xs]
    z3 = [share(w, "z3") for w in xs]
    z45 = [share(w, "z45") for w in xs]

    fig, ax = plt.subplots(figsize=(10, 3.8))
    ax.bar(xs, z12, width=5.0, color=CAT["blue"], label="Z1+Z2 (easy)")
    ax.bar(xs, z3, width=5.0, bottom=z12, color=CAT["yellow"], label="Z3 (grey zone)")
    bottom3 = [a + b for a, b in zip(z12, z3)]
    ax.bar(xs, z45, width=5.0, bottom=bottom3, color=CAT["red"], label="Z4+Z5 (hard)")
    ax.axhline(75, color=GOOD, linestyle="--", linewidth=1.6)
    ax.annotate("target: >=75% Z1+Z2", xy=(xs[0], 75), xytext=(0, 4),
                textcoords="offset points", fontsize=8.5, color=GOOD)
    ax.set_ylabel("% of running time")
    ax.set_ylim(0, 108)
    ax.set_title(f"Weekly polarisation — last {len(xs)} calendar weeks (weighted by run duration; no bar = no runs)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.tick_params(axis="x", rotation=30, labelsize=8.5)
    ax.legend(loc="upper center", ncol=3, fontsize=8.5, bbox_to_anchor=(0.5, -0.28))
    fig.tight_layout()
    return img_tag(fig, alt="Weekly running polarisation")


def build_recovery_trends(recovery, days=90):
    if not recovery:
        return no_data_note("No recovery data yet.")
    cutoff = parse_date(recovery[-1]["date"]) - timedelta(days=days)
    window = [r for r in recovery if parse_date(r["date"]) >= cutoff]

    parts = []

    # Resting HR, with the derived overnight floor beside it: the floor is the recovery
    # number, and the gap between the two is the early-night load (CLAUDE.md, Data sources)
    rhr_pts = [(parse_date(r["date"]), r["resting_hr"]) for r in window if r.get("resting_hr") is not None]
    floor_pts = [(parse_date(r["date"]), r["hr_floor"]) for r in window if r.get("hr_floor") is not None]
    if rhr_pts:
        fig, ax = plt.subplots(figsize=(10, 2.8))
        ax.plot([p[0] for p in rhr_pts], [p[1] for p in rhr_pts], color=CAT["blue"], linewidth=1.6,
                label="Garmin resting HR")
        if floor_pts:
            ax.plot([p[0] for p in floor_pts], [p[1] for p in floor_pts], color=CAT["aqua"], linewidth=1.6,
                    linestyle="--", label="Overnight HR floor (lowest 2%)")
            ax.legend(loc="upper left", fontsize=8.5)
        ax.set_ylabel("bpm")
        ax.set_title(f"Resting HR and overnight HR floor — last {days} days")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.tick_params(axis="x", rotation=30, labelsize=8.5)
        fig.tight_layout()
        parts.append(img_tag(fig, alt="Resting HR and HR floor trend"))
    else:
        parts.append(no_data_note("No resting HR data in this window."))

    # Overnight HRV (sparse; only watches that record it — see CLAUDE.md)
    hrv_pts = [(parse_date(r["date"]), r["hrv_overnight"]) for r in window if r.get("hrv_overnight") is not None]
    if len(hrv_pts) >= 2:
        fig, ax = plt.subplots(figsize=(10, 2.8))
        ax.plot([p[0] for p in hrv_pts], [p[1] for p in hrv_pts], color=CAT["aqua"],
                 linewidth=1.6, marker="o", markersize=4)
        ax.set_ylabel("ms")
        ax.set_title(f"Overnight HRV, nightly average — last {days} days")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.tick_params(axis="x", rotation=30, labelsize=8.5)
        fig.tight_layout()
        parts.append(img_tag(fig, alt="Overnight HRV trend"))
    else:
        parts.append(no_data_note(
            "Not enough HRV data in this window: only a watch that records overnight HRV fills it "
            "(Forerunner 255+/Vivoactive 5 generation, after ~3 weeks of consistent wear)."))

    # Sleep duration (hours)
    sleep_pts = [(parse_date(r["date"]), r["sleep_duration_s"] / 3600) for r in window if r.get("sleep_duration_s") is not None]
    if sleep_pts:
        fig, ax = plt.subplots(figsize=(10, 2.8))
        ax.bar([p[0] for p in sleep_pts], [p[1] for p in sleep_pts], width=0.8, color=CAT["violet"])
        ax.set_ylabel("hours")
        ax.set_title(f"Sleep duration — last {days} days")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.tick_params(axis="x", rotation=30, labelsize=8.5)
        fig.tight_layout()
        parts.append(img_tag(fig, alt="Sleep duration trend"))
    else:
        parts.append(no_data_note("No sleep duration data in this window."))

    # Body battery band
    bb_pts = [(parse_date(r["date"]), r["body_battery_low"], r["body_battery_high"])
              for r in window if r.get("body_battery_low") is not None and r.get("body_battery_high") is not None]
    if bb_pts:
        fig, ax = plt.subplots(figsize=(10, 2.8))
        xs = [p[0] for p in bb_pts]
        lo = [p[1] for p in bb_pts]
        hi = [p[2] for p in bb_pts]
        ax.fill_between(xs, lo, hi, color=CAT["green"], alpha=0.25, linewidth=0)
        ax.plot(xs, hi, color=CAT["green"], linewidth=1.2, label="High")
        ax.plot(xs, lo, color=CAT["green"], linewidth=1.2, linestyle="--", label="Low")
        ax.set_ylabel("Body Battery")
        ax.set_ylim(0, 105)
        ax.set_title(f"Body Battery range — last {days} days")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.tick_params(axis="x", rotation=30, labelsize=8.5)
        ax.legend(loc="upper left", fontsize=8.5)
        fig.tight_layout()
        parts.append(img_tag(fig, alt="Body Battery range"))
    else:
        parts.append(no_data_note("No Body Battery data in this window."))

    # Overnight/day avg stress
    st_pts = [(parse_date(r["date"]), r["stress_avg"]) for r in window if r.get("stress_avg") is not None]
    if st_pts:
        fig, ax = plt.subplots(figsize=(10, 2.8))
        ax.plot([p[0] for p in st_pts], [p[1] for p in st_pts], color=CAT["orange"], linewidth=1.6)
        ax.axhline(16, color="#bbb", linestyle=":", linewidth=1)
        ax.set_ylabel("avg stress")
        ax.set_title(f"Average stress — last {days} days (target < 16)")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.tick_params(axis="x", rotation=30, labelsize=8.5)
        fig.tight_layout()
        parts.append(img_tag(fig, alt="Stress trend"))

    # Garmin training readiness (newer watches only; sparse)
    tr_pts = [(parse_date(r["date"]), r["training_readiness"]) for r in window if r.get("training_readiness") is not None]
    if len(tr_pts) >= 2:
        fig, ax = plt.subplots(figsize=(10, 2.8))
        ax.plot([p[0] for p in tr_pts], [p[1] for p in tr_pts], color=CAT["blue"],
                 linewidth=1.6, marker="o", markersize=3)
        ax.set_ylabel("readiness")
        ax.set_ylim(0, 100)
        ax.set_title("Garmin training readiness")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.tick_params(axis="x", rotation=30, labelsize=8.5)
        fig.tight_layout()
        parts.append(img_tag(fig, alt="Training readiness trend"))

    # Overnight respiration (avg + low/high band) — a rise flags illness / alcohol / overreaching
    rsp_pts = [(parse_date(r["date"]), r.get("resp_sleep_avg"), r.get("resp_sleep_low"), r.get("resp_sleep_high"))
               for r in window if r.get("resp_sleep_avg") is not None]
    if len(rsp_pts) >= 2:
        fig, ax = plt.subplots(figsize=(10, 2.8))
        xs = [p[0] for p in rsp_pts]
        ax.plot(xs, [p[1] for p in rsp_pts], color=CAT["aqua"], linewidth=1.6)
        if all(p[2] is not None and p[3] is not None for p in rsp_pts):
            ax.fill_between(xs, [p[2] for p in rsp_pts], [p[3] for p in rsp_pts],
                            color=CAT["aqua"], alpha=0.15, linewidth=0)
        ax.set_ylabel("breaths/min")
        ax.set_title(f"Overnight respiration — last {days} days (a rise = illness/alcohol flag)")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.tick_params(axis="x", rotation=30, labelsize=8.5)
        fig.tight_layout()
        parts.append(img_tag(fig, alt="Respiration trend"))

    return '<div class="recovery-grid">' + "\n".join(f'<div class="rc-panel">{p}</div>' for p in parts) + "</div>"


def build_cross_training(cardio, rowing, weeks=16):
    """Weekly minutes of non-run aerobic cross-training (cardio_log.jsonl), plus rowing
    if a rowing_log.jsonl exists: the aerobic work the running charts never see."""
    cardio_wk, row_wk = defaultdict(float), defaultdict(float)
    for c in cardio:
        d, mins = c.get("date"), c.get("duration_min")
        if d and mins:
            cardio_wk[week_start(parse_date(d))] += mins
    for r in rowing:
        d, secs = r.get("date"), r.get("work_time_s")
        if d and secs:
            row_wk[week_start(parse_date(d))] += secs / 60
    if not cardio_wk and not row_wk:
        return no_data_note("No cross-training or rowing logged yet.")
    allweeks = last_calendar_weeks(weeks)
    fig, ax = plt.subplots(figsize=(10, 3.4))
    cvals = [cardio_wk.get(w, 0) for w in allweeks]
    rvals = [row_wk.get(w, 0) for w in allweeks]
    ax.bar(allweeks, cvals, width=5.0, color=CAT["violet"], label="Cross-training (elliptical/bike/etc.)")
    if row_wk:   # rowing_log.jsonl is optional (see README, Related projects)
        ax.bar(allweeks, rvals, width=5.0, bottom=cvals, color=CAT["aqua"], label="Rowing")
    ax.set_ylabel("minutes/week")
    ax.set_title(f"Cross-training volume — last {len(allweeks)} calendar weeks (a missing bar is a zero week)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.tick_params(axis="x", rotation=30, labelsize=8.5)
    ax.legend(loc="upper left", fontsize=8.5)
    fig.tight_layout()
    note = ('<p style="font-size:0.82rem;color:#888;margin:0.3rem 0 0;">'
            'Aerobic work that is not running: build_run_log.py never sees it, so it is '
            'counted here rather than lost.</p>')
    return img_tag(fig, alt="Cross-training and rowing volume") + "\n" + note


def build_fitness_trends(recovery):
    if not recovery:
        return no_data_note("No recovery data yet.")

    parts = []

    # VO2max, carry-forward across nulls (only written on outdoor-GPS-run days)
    vo2_pts = []
    last = None
    for r in recovery:
        if r.get("vo2max") is not None:
            last = r["vo2max"]
        if last is not None:
            vo2_pts.append((parse_date(r["date"]), last))
    if vo2_pts:
        fig, ax = plt.subplots(figsize=(10, 2.8))
        ax.plot([p[0] for p in vo2_pts], [p[1] for p in vo2_pts], color=CAT["blue"], linewidth=1.6)
        ax.set_ylabel("VO2max")
        ax.set_title("VO2max over time (carried forward between updates — only computed on outdoor GPS runs)")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        ax.tick_params(axis="x", rotation=30, labelsize=8.5)
        fig.tight_layout()
        parts.append(img_tag(fig, alt="VO2max trend"))
    else:
        parts.append(no_data_note("No VO2max data yet."))

    # 5k race prediction (Garmin daily race predictor; present once your watch supports it)
    r5k_pts = [(parse_date(r["date"]), r["race_5k_s"]) for r in recovery if r.get("race_5k_s") is not None]
    if r5k_pts:
        fig, ax = plt.subplots(figsize=(10, 2.8))
        xs = [p[0] for p in r5k_pts]
        ys = [p[1] for p in r5k_pts]
        ax.plot(xs, ys, color=CAT["orange"], linewidth=1.6)
        ax.set_ylabel("predicted 5k time")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, pos: fmt_mmss(v)))
        ax.invert_yaxis()  # faster (lower seconds) reads as "up"
        ax.set_title("Garmin 5k race prediction (decays without fresh outdoor pace-at-HR data)")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.tick_params(axis="x", rotation=30, labelsize=8.5)
        fig.tight_layout()
        parts.append(img_tag(fig, alt="5k race prediction trend"))
    else:
        parts.append(no_data_note("No 5k race-prediction data yet."))

    return '<div class="recovery-grid">' + "\n".join(f'<div class="rc-panel">{p}</div>' for p in parts) + "</div>"


def build_power_dynamics(runs):
    pts = [(parse_date(r["date"]), r["garmin"]) for r in runs if r.get("garmin")]
    if not pts:
        return no_data_note("No running-power/dynamics data — needs a watch that records them (Forerunner 255+/265 generation).")

    parts = []
    power_pts = [(d, g["avg_power"]) for d, g in pts if g.get("avg_power") is not None]
    if power_pts:
        fig, ax = plt.subplots(figsize=(10, 2.8))
        ax.plot([p[0] for p in power_pts], [p[1] for p in power_pts], marker="o", markersize=4,
                 color=CAT["blue"], linewidth=1.6)
        ax.set_ylabel("watts")
        ax.set_title("Avg running power")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.tick_params(axis="x", rotation=30, labelsize=8.5)
        fig.tight_layout()
        parts.append(img_tag(fig, alt="Avg running power"))

    cad_pts = [(d, g["avg_cadence_spm"]) for d, g in pts if g.get("avg_cadence_spm") is not None]
    if cad_pts:
        fig, ax = plt.subplots(figsize=(10, 2.8))
        ax.plot([p[0] for p in cad_pts], [p[1] for p in cad_pts], marker="o", markersize=4,
                 color=CAT["aqua"], linewidth=1.6)
        ax.set_ylabel("spm")
        ax.set_title("Avg cadence")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.tick_params(axis="x", rotation=30, labelsize=8.5)
        fig.tight_layout()
        parts.append(img_tag(fig, alt="Avg cadence"))

    if not parts:
        return no_data_note("Runs found but no power/cadence values populated yet.")

    note = ('<div class="note">Power + running dynamics only exist for runs recorded on a watch that '
            'supports them (Forerunner 255+/265 generation); ground-contact and vertical-oscillation '
            'additionally need a compatible HR strap or pod.</div>')
    return note + '<div class="recovery-grid">' + "\n".join(f'<div class="rc-panel">{p}</div>' for p in parts) + "</div>"


def build_plan_panel(plan_text):
    trajectory = extract_section(plan_text, "## Trajectory (next few months)")
    squat = extract_section(plan_text, "## Squat progression (top set, Wednesday)")
    html = ['<div class="plan-grid">']
    html.append('<div class="plan-col"><h3>Trajectory — roadmap to October</h3>')
    html.append(md_to_html(trajectory))
    html.append("</div>")
    html.append('<div class="plan-col"><h3>Squat progression (double progression)</h3>')
    html.append(md_to_html(squat))
    html.append("</div>")
    html.append("</div>")
    return "\n".join(html)


# ---------------------------------------------------------------------------
# Page assembly
# ---------------------------------------------------------------------------

CSS = """
:root {
  --surface: #fcfcfb; --page: #f5f4f0; --ink: #0b0b0b; --ink-2: #52514e;
  --ink-muted: #898781; --border: rgba(11,11,11,0.10); --grid: #e1e0d9;
  --accent: #2a78d6; --card-shadow: 0 1px 2px rgba(11,11,11,0.06), 0 1px 8px rgba(11,11,11,0.04);
}
@media (prefers-color-scheme: dark) {
  :root {
    --surface: #1f1f1d; --page: #131312; --ink: #f5f5f3; --ink-2: #c3c2b7;
    --ink-muted: #8f8d87; --border: rgba(255,255,255,0.10); --grid: #2c2c2a;
    --accent: #3987e5; --card-shadow: 0 1px 2px rgba(0,0,0,0.3), 0 1px 10px rgba(0,0,0,0.25);
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0 0 4rem;
  background: var(--page); color: var(--ink);
  font-family: -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  line-height: 1.5;
}
.wrap { max-width: 1180px; margin: 0 auto; padding: 2rem 1.5rem; }
header.page-header { margin-bottom: 1.75rem; }
header.page-header h1 { margin: 0 0 0.25rem; font-size: 1.7rem; letter-spacing: -0.01em; }
.freshness { color: var(--ink-2); font-size: 0.92rem; }
section { margin-bottom: 2.75rem; }
section > h2 {
  font-size: 1.05rem; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--ink-2); border-bottom: 1px solid var(--border);
  padding-bottom: 0.5rem; margin: 0 0 1.1rem;
}
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 0.9rem; }
.card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 0.95rem 1.05rem; box-shadow: var(--card-shadow);
}
.card-title { font-size: 0.78rem; color: var(--ink-muted); text-transform: uppercase; letter-spacing: 0.03em; }
.card-value { font-size: 1.5rem; font-weight: 650; margin: 0.15rem 0; }
.card-sub { font-size: 0.78rem; color: var(--ink-2); }
.chart { display: block; width: 100%; height: auto; border-radius: 8px; margin: 0.3rem 0 0.9rem; }
.recovery-grid, .plan-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 0 1.2rem; }
.rc-panel .chart { margin-bottom: 0.4rem; }
.no-data {
  padding: 1.4rem; text-align: center; color: var(--ink-muted); font-size: 0.9rem;
  background: var(--surface); border: 1px dashed var(--border); border-radius: 8px;
}
.note { font-size: 0.82rem; color: var(--ink-muted); margin-bottom: 0.6rem; }
table.sessions { width: 100%; border-collapse: collapse; background: var(--surface);
  border: 1px solid var(--border); border-radius: 10px; overflow: hidden; font-size: 0.86rem; }
table.sessions th, table.sessions td { text-align: left; padding: 0.55rem 0.8rem; border-bottom: 1px solid var(--border); vertical-align: top; }
table.sessions th { color: var(--ink-muted); font-weight: 600; text-transform: uppercase; font-size: 0.72rem; letter-spacing: 0.03em; }
table.sessions tr:last-child td { border-bottom: none; }
.nowrap { white-space: nowrap; }
.summary { color: var(--ink-2); }
.plan-col { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 1rem 1.2rem; margin-bottom: 1rem; }
.plan-col h3 { margin-top: 0; font-size: 1rem; }
.plan-col ul { padding-left: 1.15rem; margin: 0.4rem 0; }
.plan-col li { margin-bottom: 0.5rem; font-size: 0.9rem; }
.plan-col p { font-size: 0.9rem; }
footer.page-footer { color: var(--ink-muted); font-size: 0.78rem; text-align: center; margin-top: 2.5rem; }
@media (max-width: 640px) {
  .wrap { padding: 1.25rem 1rem; }
  header.page-header h1 { font-size: 1.35rem; }
}
"""


def build_dashboard_html(sessions, runs, recovery, weight, plan_text, cardio, rowing):
    dates_present = []
    if sessions:
        dates_present.append(max(s["session_date"] for s in sessions))
    if runs:
        dates_present.append(max(r["date"] for r in runs))
    if recovery:
        dates_present.append(max(r["date"] for r in recovery))
    freshness = max(dates_present) if dates_present else "no data"

    body = f"""
<div class="wrap">
  <header class="page-header">
    <h1>Training Dashboard</h1>
    <div class="freshness">Latest data: {esc(freshness)} &middot; generated from strength_log.jsonl, run_log.jsonl, recovery_log.jsonl, TRAINING_PLAN.md</div>
  </header>

  <section id="snapshot">
    <h2>Snapshot</h2>
    {build_snapshot_cards(sessions, runs, recovery, weight)}
  </section>

  <section id="strength-progression">
    <h2>Strength progression</h2>
    {build_strength_progression(sessions)}
  </section>

  <section id="recent-sessions">
    <h2>Recent strength sessions</h2>
    {build_recent_sessions_table(sessions)}
  </section>

  <section id="running-volume">
    <h2>Running volume</h2>
    {build_running_volume(runs)}
  </section>

  <section id="polarisation">
    <h2>Polarisation</h2>
    {build_polarisation(runs)}
  </section>

  <section id="cross-training">
    <h2>Cross-training</h2>
    {build_cross_training(cardio, rowing)}
  </section>

  <section id="recovery-trends">
    <h2>Recovery trends</h2>
    {build_recovery_trends(recovery)}
  </section>

  <section id="fitness-trends">
    <h2>Fitness trends</h2>
    {build_fitness_trends(recovery)}
  </section>

  <section id="bodyweight">
    <h2>Bodyweight</h2>
    {build_weight_trend(weight)}
  </section>

  <section id="power-dynamics">
    <h2>Running power &amp; dynamics</h2>
    {build_power_dynamics(runs)}
  </section>

  <section id="plan">
    <h2>Upcoming cycles / plan</h2>
    {build_plan_panel(plan_text)}
  </section>

  <footer class="page-footer">Rebuild with <code>.venv/bin/python scripts/build_dashboard.py</code> — regenerated wholesale from the durable JSONL logs each run.</footer>
</div>
"""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Training Dashboard</title>
<style>{CSS}</style>
</head>
<body>
{body}
</body>
</html>
"""


def main():
    set_style()
    sessions = load_strength()
    runs = load_runs()
    recovery = load_recovery()
    weight = load_weight()
    cardio = load_cardio()
    rowing = load_rowing()
    plan_text = (ROOT / "TRAINING_PLAN.md").read_text()

    html = build_dashboard_html(sessions, runs, recovery, weight, plan_text, cardio, rowing)
    OUT.write_text(html)

    size_kb = OUT.stat().st_size / 1024
    counted_runs = sum(1 for r in runs if r.get("counts_as_run"))
    dates = [r["date"] for r in recovery] if recovery else []
    print(f"Wrote {OUT.relative_to(ROOT)} ({size_kb:.0f} KB)")
    print(f"  Strength sessions (post-corrections): {len(sessions)}")
    print(f"  Runs: {len(runs)} total, {counted_runs} count_as_run")
    if dates:
        print(f"  Recovery data range: {dates[0]} to {dates[-1]} ({len(dates)} days)")
    else:
        print("  Recovery data: none")


if __name__ == "__main__":
    main()
