"""Backfill detailed activity data + streams for recent activities.

Usage:
    python scripts/backfill_details.py            # last 250, with streams
    python scripts/backfill_details.py --limit 100
    python scripts/backfill_details.py --no-streams
    python scripts/backfill_details.py --all      # every activity (slow)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv

load_dotenv()

from fitness import strava_detail
from fitness.db import init

parser = argparse.ArgumentParser()
parser.add_argument("--limit", type=int, default=250)
parser.add_argument("--all", action="store_true")
parser.add_argument("--no-streams", action="store_true")
args = parser.parse_args()

init()
limit = None if args.all else args.limit
counts = strava_detail.backfill(limit=limit, include_streams=not args.no_streams)
print("Done:", counts)
