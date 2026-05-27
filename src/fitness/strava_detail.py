"""Pull detailed activity data + streams from Strava.

Strava rate limits: 200 requests / 15 min, 2000 / day. Each activity is 2 calls
(detail + streams), so budget ~1000 activities/day worst case. This script
pauses when it hits the short-window limit.
"""
import json
import os
import time
from datetime import datetime, timezone

from stravalib import Client
from stravalib.exc import RateLimitExceeded, Fault

from .db import connect

STREAM_TYPES = [
    "time", "heartrate", "watts", "cadence",
    "velocity_smooth", "altitude", "distance", "temp",
]


def _client() -> Client:
    c = Client()
    token = c.refresh_access_token(
        client_id=int(os.environ["STRAVA_CLIENT_ID"]),
        client_secret=os.environ["STRAVA_CLIENT_SECRET"],
        refresh_token=os.environ["STRAVA_REFRESH_TOKEN"],
    )
    c.access_token = token["access_token"]
    return c


def _needs_detail(conn, activity_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM activity_details WHERE activity_id = ?", (activity_id,)
    ).fetchone()
    return row is None


def _needs_streams(conn, activity_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM activity_streams WHERE activity_id = ?", (activity_id,)
    ).fetchone()
    return row is None


def backfill(limit: int | None = 250, include_streams: bool = True) -> dict:
    """Fetch detail + streams for the most recent `limit` activities missing them.

    limit=None means all. Safely resumable — already-fetched activities are skipped.
    """
    client = _client()
    with connect() as conn:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM activities ORDER BY start_time DESC"
        ).fetchall()]

    counts = {"detail": 0, "streams": 0, "skipped": 0, "errors": 0}
    processed = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for activity_id in ids:
        if limit is not None and processed >= limit:
            break
        processed += 1

        with connect() as conn:
            need_d = _needs_detail(conn, activity_id)
            need_s = include_streams and _needs_streams(conn, activity_id)

        if not need_d and not need_s:
            counts["skipped"] += 1
            continue

        try:
            if need_d:
                a = client.get_activity(activity_id)
                laps = [l.model_dump(mode="json") for l in (a.laps or [])]
                bests = [b.model_dump(mode="json") for b in (a.best_efforts or [])]
                with connect() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO activity_details "
                        "(activity_id, fetched_at, description, gear_id, device_name, "
                        " calories, laps_json, best_efforts_json, raw_json) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            activity_id, now_iso, a.description, a.gear_id,
                            a.device_name, a.calories,
                            json.dumps(laps), json.dumps(bests),
                            a.model_dump_json(),
                        ),
                    )
                counts["detail"] += 1

            if need_s:
                streams = client.get_activity_streams(
                    activity_id, types=STREAM_TYPES, resolution="medium"
                ) or {}
                flat = {k: v.data for k, v in streams.items()}
                with connect() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO activity_streams "
                        "(activity_id, fetched_at, resolution, streams_json) "
                        "VALUES (?,?,?,?)",
                        (activity_id, now_iso, "medium", json.dumps(flat)),
                    )
                counts["streams"] += 1

        except RateLimitExceeded as e:
            print(f"Rate limit hit at activity {activity_id}. Sleeping 15 min.")
            time.sleep(15 * 60 + 10)
            continue
        except Fault as e:
            print(f"  skip {activity_id}: {e}")
            counts["errors"] += 1
            continue

        if processed % 25 == 0:
            print(f"  processed {processed}: {counts}")

    return counts
