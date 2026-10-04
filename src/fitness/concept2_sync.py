"""Concept2 Logbook API sync: pulls your erg results into a local raw cache.

Optional, for those who row. The Logbook is the authoritative source for erg
workouts: it carries drag factor, stroke rate and count, and interval splits that
neither Strava nor Garmin keep. `scripts/build_rowing_log.py` merges this cache with
any Logbook CSV exports in data/concept2_csv/, deduping on log ID, into the durable
data/rowing_log.jsonl.

Auth: register an API application with Concept2, put its ID and secret in .env, and
run scripts/concept2_auth.py once to obtain CONCEPT2_REFRESH_TOKEN. Access is
read-only (user:read, results:read). scripts/sync.py runs incremental() whenever
the three credentials are set, and skips Concept2 otherwise.

The raw cache (data/concept2_api_cache.json) is rebuildable from the API;
rowing_log.jsonl is the durable record, the same pattern as the Strava/Garmin DB.

Usage:
    from fitness import concept2_sync
    concept2_sync.sync()                 # everything the API will give
    concept2_sync.sync(updated_after="2026-07-01")
    concept2_sync.incremental()          # from a week before the newest cached result
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from .envfile import require, set_env_var

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "concept2_api_cache.json"

API = "https://log.concept2.com/api"
TOKEN_URL = "https://log.concept2.com/oauth/access_token"
SCOPES = "user:read,results:read"  # must match scripts/concept2_auth.py
KEYS = ("CONCEPT2_CLIENT_ID", "CONCEPT2_CLIENT_SECRET", "CONCEPT2_REFRESH_TOKEN")


def configured() -> bool:
    """Whether the Logbook link is set up (client ID, secret and a refresh token in .env)."""
    return all(os.environ.get(k) for k in KEYS)


def _access_token() -> str:
    """Exchange the stored refresh token for a short-lived access token."""
    refresh = require("CONCEPT2_REFRESH_TOKEN")
    data = urllib.parse.urlencode({
        "client_id": require("CONCEPT2_CLIENT_ID"),
        "client_secret": require("CONCEPT2_CLIENT_SECRET"),
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "scope": SCOPES,
    }).encode()
    try:
        resp = json.loads(urllib.request.urlopen(
            urllib.request.Request(TOKEN_URL, data=data)).read())
    except urllib.error.HTTPError as e:   # say why: a dead token reads "The refresh token is invalid"
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        raise RuntimeError(f"token refresh failed, HTTP {e.code}: "
                           f"{body.get('message') or body.get('error_description') or e.reason}") from None
    # Concept2 issues a fresh refresh token on every refresh and the old one stops
    # working, so the new one must be saved or the next sync fails with "The refresh
    # token is invalid". set_env_var writes .env atomically.
    new_refresh = resp.get("refresh_token")
    if new_refresh and new_refresh != refresh:
        set_env_var("CONCEPT2_REFRESH_TOKEN", new_refresh, ROOT / ".env")
    return resp["access_token"]


def _get(path: str, token: str, **params) -> dict:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    return json.loads(urllib.request.urlopen(req).read())


def fetch_results(updated_after: str | None = None, page_size: int = 250) -> list:
    """All results, following pagination. `updated_after` makes syncs cheap."""
    token = _access_token()
    out, page = [], 1
    while True:
        payload = _get("/users/me/results", token,
                       updated_after=updated_after, number=page_size, page=page)
        rows = payload.get("data") or []
        out.extend(rows)
        pg = (payload.get("meta") or {}).get("pagination") or {}
        if page >= (pg.get("total_pages") or 1) or not rows:
            break
        page += 1
    return out


def sync(updated_after: str | None = None) -> int:
    """Fetch results and merge them into the raw cache, keyed by log id."""
    fresh = fetch_results(updated_after=updated_after)
    cache = {}
    if CACHE.exists():
        cache = {str(r["id"]): r for r in json.loads(CACHE.read_text())}
    for r in fresh:
        cache[str(r["id"])] = r
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(sorted(
        cache.values(), key=lambda r: str(r.get("date", ""))), indent=1))
    return len(fresh)


def incremental(overlap_days: int = 7) -> int:
    """sync() from `overlap_days` before the newest cached result, or everything on a first
    run. The overlap re-fetches recent results, so a comment or correction made in the
    Logbook since the last sync still arrives."""
    since = None
    if CACHE.exists():
        dates = [str(r.get("date") or "")[:10] for r in json.loads(CACHE.read_text())]
        dates = [d for d in dates if len(d) == 10]
        if dates:
            since = (date.fromisoformat(max(dates)) - timedelta(days=overlap_days)).isoformat()
    return sync(updated_after=since)
