import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv

load_dotenv()

from fitness import strava_sync, garmin_sync, garmin_activities, strength
from fitness.db import init

init()
try:
    print(f"Strava: {strava_sync.sync(days=None)} activities")  # full history
    print(f"Garmin: {garmin_sync.sync(days=365)} days")
    print(f"Garmin activities: {garmin_activities.sync()} run metrics cached")
except RuntimeError as e:   # a missing credential: say which, without a traceback
    sys.exit(f"sync: {e}")
print(f"Strength: {strength.ingest()} new sessions")
