import hashlib
import json
from pathlib import Path

from .db import connect

LOG_PATH = Path(__file__).resolve().parents[2] / "data" / "strength_log.jsonl"


def ingest() -> int:
    if not LOG_PATH.exists():
        return 0
    inserted = 0
    with connect() as conn, LOG_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            h = hashlib.sha256(line.encode()).hexdigest()
            entry = json.loads(line)
            cur = conn.execute(
                "INSERT OR IGNORE INTO strength_sessions "
                "(logged_at, session_date, session_label, notes, source_line_hash) "
                "VALUES (?,?,?,?,?)",
                (
                    entry["logged_at"],
                    entry["session_date"],
                    entry.get("session_label"),
                    entry.get("notes"),
                    h,
                ),
            )
            if cur.rowcount == 0:
                continue
            session_id = cur.lastrowid
            set_rows = []
            for ex in entry.get("exercises", []):
                for i, s in enumerate(ex.get("sets", [])):
                    set_rows.append((
                        session_id,
                        ex["name"],
                        i,
                        s.get("reps"),
                        s.get("weight_kg"),
                        s.get("rpe"),
                        ex.get("notes"),
                    ))
            conn.executemany(
                "INSERT INTO strength_sets "
                "(session_id, exercise, set_index, reps, weight_kg, rpe, notes) "
                "VALUES (?,?,?,?,?,?,?)",
                set_rows,
            )
            inserted += 1
    return inserted
