import json
import os
from datetime import datetime, timezone

from stravalib import Client

from .db import connect


def _client() -> Client:
    c = Client()
    token = c.refresh_access_token(
        client_id=int(os.environ["STRAVA_CLIENT_ID"]),
        client_secret=os.environ["STRAVA_CLIENT_SECRET"],
        refresh_token=os.environ["STRAVA_REFRESH_TOKEN"],
    )
    c.access_token = token["access_token"]
    return c


def sync(days: int | None = None) -> int:
    """Sync Strava activities. days=None pulls full history."""
    client = _client()
    after = 0 if days is None else datetime.now(timezone.utc).timestamp() - days * 86400
    rows = []
    for a in client.get_activities(after=after):
        rows.append((
            a.id,
            "strava",
            a.start_date.isoformat() if a.start_date else None,
            (a.sport_type.root if a.sport_type else (a.type.root if a.type else None)),
            a.name,
            float(a.distance) if a.distance else None,
            int(a.moving_time) if a.moving_time is not None else None,
            int(a.elapsed_time) if a.elapsed_time is not None else None,
            float(a.total_elevation_gain) if a.total_elevation_gain else None,
            a.average_heartrate,
            a.max_heartrate,
            a.average_watts,
            a.kilojoules,
            a.suffer_score,
            a.model_dump_json(),
        ))
    with connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO activities VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)
