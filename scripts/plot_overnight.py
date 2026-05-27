"""Plot overnight HR and stress from Garmin intraday data.

Usage:
    python scripts/plot_overnight.py 2026-04-21
    # (date is the evening you went to bed; plot spans 22:30 that day to 09:00 next day)
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import pytz

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fitness.garmin_intraday import load

# Set your local timezone here, or via the TZ_NAME environment variable.
TZ_NAME = os.environ.get("TZ_NAME", "UTC")
TZ = pytz.timezone(TZ_NAME)


def series(ds: str, stream: str, value_key_candidates: list[str]):
    d = load(ds, stream) or {}
    vals = None
    for k in value_key_candidates:
        if k in d and d[k]:
            vals = d[k]
            break
    if not vals:
        return pd.DataFrame(columns=["t", "value"])
    df = pd.DataFrame(vals, columns=["ts_ms", "value"]).dropna()
    df["t"] = (
        pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
        .dt.tz_convert(TZ_NAME)
    )
    return df[["t", "value"]]


def main(bed_date: str):
    bed = datetime.strptime(bed_date, "%Y-%m-%d")
    next_day = (bed + timedelta(days=1)).strftime("%Y-%m-%d")

    hr = pd.concat([
        series(bed_date, "heartrate", ["heartRateValues"]),
        series(next_day, "heartrate", ["heartRateValues"]),
    ]).drop_duplicates("t").sort_values("t")

    st = pd.concat([
        series(bed_date, "stress", ["stressValuesArray", "stressValues"]),
        series(next_day, "stress", ["stressValuesArray", "stressValues"]),
    ]).drop_duplicates("t").sort_values("t")

    start = TZ.localize(bed.replace(hour=22, minute=30))
    end = TZ.localize((bed + timedelta(days=1)).replace(hour=9, minute=0))

    hr_n = hr[(hr["t"] >= start) & (hr["t"] <= end)].copy()

    if hr_n.empty:
        print("No overnight HR data.")
        return

    print(
        f"HR samples: {len(hr_n)}   "
        f"min={hr_n['value'].min():.0f}, median={hr_n['value'].median():.0f}, "
        f"max={hr_n['value'].max():.0f}"
    )

    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(hr_n["t"], hr_n["value"], color="crimson", lw=1)
    ax.axhline(
        hr_n["value"].median(), color="grey", ls="--", alpha=0.5,
        label=f"median {hr_n['value'].median():.0f} bpm",
    )
    ax.set_ylabel("Heart rate (bpm)")
    ax.set_xlabel("Local time")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper right")
    ax.set_title(f"Overnight HR  {bed_date} → {next_day}")

    ax.xaxis.set_major_locator(mdates.HourLocator(interval=1, tz=TZ))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=TZ))
    ax.set_xlim(start, end)
    fig.tight_layout()
    out = Path("data") / f"overnight_{bed_date}.png"
    fig.savefig(out, dpi=130)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2026-04-21")
