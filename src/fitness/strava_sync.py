# MIGRATION (before 1 June 2027): Strava API changes take effect — auth tokens
# must be sent in request headers (not form params), base URL moves from
# www.strava.com/api/v3 -> www.api-v3.strava.com, and oauth/deauthorize -> oauth/revoke.
# All handled inside stravalib, not this code: just `pip install -U stravalib`
# before then. (The 30 June 2026 subscription requirement is already satisfied.)
import json
import os
from datetime import datetime, timedelta, timezone

from stravalib import Client

from .db import connect
from .envfile import require, set_env_var


def client() -> Client:
    """A logged-in stravalib client.

    Strava's docs say of the refresh token: "expect that this value can change anytime
    you retrieve a new access token", after which the old one stops working. So a changed
    token is written straight back to .env (a sync that throws the rotated token away
    dies quietly the next time it runs)."""
    c = Client()
    token = c.refresh_access_token(
        client_id=int(require("STRAVA_CLIENT_ID")),
        client_secret=require("STRAVA_CLIENT_SECRET"),
        refresh_token=require("STRAVA_REFRESH_TOKEN"),
    )
    c.access_token = token["access_token"]
    new = token.get("refresh_token")
    if new and new != os.environ.get("STRAVA_REFRESH_TOKEN"):
        set_env_var("STRAVA_REFRESH_TOKEN", new)
    return c


_client = client


def sync(days: int | None = None) -> int:
    """Sync Strava activities. days=None pulls full history."""
    client = _client()
    # stravalib expects a datetime (or None); a bare epoch float trips its
    # isinstance check, so None for full history, a datetime for a window.
    after = None if days is None else datetime.now(timezone.utc) - timedelta(days=days)
    rows = []
    for a in client.get_activities(after=after):
        rows.append((
            a.id,
            "strava",
            a.start_date.isoformat() if a.start_date else None,
            (a.sport_type.root if a.sport_type else (a.type.root if a.type else None)),
            a.name,
            # `is not None`, not truthiness: a flat or treadmill run reports 0 m of climb,
            # and 0 is a measurement, not a missing value (142 runs were stored NULL before).
            float(a.distance) if a.distance is not None else None,
            int(a.moving_time) if a.moving_time is not None else None,
            int(a.elapsed_time) if a.elapsed_time is not None else None,
            float(a.total_elevation_gain) if a.total_elevation_gain is not None else None,
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
