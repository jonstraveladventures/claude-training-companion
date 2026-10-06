import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv

load_dotenv()

from fitness import strava_sync, garmin_sync, garmin_activities, strength, concept2_sync
from fitness.db import init

init()
try:
    print(f"Strava: {strava_sync.sync(days=None)} activities")  # full history
    print(f"Garmin: {garmin_sync.sync(days=365)} days")
    print(f"Garmin activities: {garmin_activities.sync()} run metrics cached")
except RuntimeError as e:   # a missing credential: say which, without a traceback
    sys.exit(f"sync: {e}")
if concept2_sync.configured():   # optional: only for those who row and set up the Logbook link
    try:
        # The full listing (one request per 250 results) lets a Logbook deletion reach the cache.
        print(f"Concept2: {concept2_sync.sync()} results")
    except (RuntimeError, OSError, ValueError) as e:   # urllib's HTTP errors are OSErrors
        print(f"Concept2: skipped ({str(e).rstrip('.')}). If the refresh token is invalid, "
              "re-run scripts/concept2_auth.py.")
print(f"Strength: {strength.ingest()} new sessions")
