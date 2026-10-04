"""Merge a rebuilt activity log with the copy already on disk.

run_log.jsonl and cardio_log.jsonl are built from the SQLite DB, which is a cache: after
a rebuild, streams and the Garmin per-run cache are refetched only for recent activities,
and the Strava sync may not reach back as far as the log does. Writing the rebuilt list
straight over the file would blank zones, drift and running power for every older
activity, and drop activities the DB no longer holds. These logs exist to survive exactly
that, so the builders merge instead.
"""
import json
from pathlib import Path

# Fields describing how records relate rather than what was measured: always rebuilt.
STRUCTURAL = {"merged_ids"}


def load(path: Path, key: str = "activity_id") -> dict:
    if not path.exists():
        return {}
    return {r[key]: r for r in
            (json.loads(l) for l in path.read_text().splitlines() if l.strip())}


def merge(records: list, existing: dict, db_ids: set, key: str = "activity_id",
          keep=lambda rec: False) -> tuple[list, int]:
    """Fill each rebuilt field that came back None from the archived record, and keep an
    archived record the rebuild didn't produce when its activity is absent from the DB
    (the rebuild didn't reach back that far) or when keep(record) says so (it holds
    hand-entered readings that exist nowhere else). An archived record whose activity IS
    in the DB but wasn't built (merged into a twin, re-typed, now too short) is dropped.
    Returns (records, number kept from the archive only)."""
    merged_away = {i for r in records for i in (r.get("merged_ids") or [])}
    for r in records:
        old = existing.get(r[key]) or {}
        for k, v in old.items():
            if k in r and k not in STRUCTURAL and r[k] is None and v is not None:
                r[k] = v
    built = {r[key] for r in records}
    kept = [old for k, old in existing.items()
            if k not in built and k not in merged_away and (k not in db_ids or keep(old))]
    if kept:
        records = sorted(records + kept, key=lambda r: r.get("start_time") or "")
    return records, len(kept)
