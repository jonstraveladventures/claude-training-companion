"""Pull raw intraday time-series from Garmin Connect.

Streams stored as JSON blobs keyed by (date, stream). Endpoints are
undocumented and occasionally change shape — we store the raw response so we
can re-parse later without re-hitting the API.
"""
import json
import os
from datetime import date, datetime, timezone

from garminconnect import Garmin

from .db import connect

STREAMS = ["heartrate", "stress", "respiration", "spo2", "body_battery", "hrv"]


def _client() -> Garmin:
    g = Garmin(os.environ["GARMIN_EMAIL"], os.environ["GARMIN_PASSWORD"])
    g.login()
    return g


def _fetch_one(g: Garmin, stream: str, ds: str):
    if stream == "heartrate":
        return g.get_heart_rates(ds)
    if stream == "stress":
        return g.get_stress_data(ds)
    if stream == "respiration":
        return g.get_respiration_data(ds)
    if stream == "spo2":
        return g.get_spo2_data(ds)
    if stream == "body_battery":
        return g.get_body_battery(ds)
    if stream == "hrv":
        return g.get_hrv_data(ds)
    raise ValueError(stream)


def pull(ds: str, streams: list[str] | None = None) -> dict:
    """Pull raw intraday streams for one date. Returns counts by stream."""
    g = _client()
    now = datetime.now(timezone.utc).isoformat()
    results = {}
    to_fetch = streams or STREAMS
    with connect() as conn:
        for s in to_fetch:
            try:
                data = _fetch_one(g, s, ds)
            except Exception as e:
                results[s] = f"error: {e}"
                continue
            if data is None:
                results[s] = "empty"
                continue
            conn.execute(
                "INSERT OR REPLACE INTO garmin_intraday (date, stream, raw_json, fetched_at) VALUES (?,?,?,?)",
                (ds, s, json.dumps(data, default=str), now),
            )
            results[s] = "ok"
    return results


def load(ds: str, stream: str):
    with connect() as conn:
        row = conn.execute(
            "SELECT raw_json FROM garmin_intraday WHERE date = ? AND stream = ?",
            (ds, stream),
        ).fetchone()
    return json.loads(row[0]) if row else None
