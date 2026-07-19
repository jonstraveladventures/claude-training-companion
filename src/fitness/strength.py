import hashlib
import json
from pathlib import Path

from .db import connect

LOG_PATH = Path(__file__).resolve().parents[2] / "data" / "strength_log.jsonl"


def ingest() -> int:
    if not LOG_PATH.exists():
        return 0
    entries = [(l, json.loads(l)) for l in
               (ln.strip() for ln in LOG_PATH.read_text().splitlines()) if l]
    # correction_of supersession: a later entry with correction_of=<logged_at>
    # replaces that original, which must NOT live in the DB or it double-counts.
    # The two committed builders already honour this; ingest() must too.
    superseded = {e.get("correction_of") for _, e in entries if e.get("correction_of")}
    inserted = 0
    with connect() as conn:
        # Purge any superseded originals a prior ingest already inserted.
        if superseded:
            ph = ",".join("?" * len(superseded))
            ids = [r[0] for r in conn.execute(
                f"SELECT id FROM strength_sessions WHERE logged_at IN ({ph})",
                tuple(superseded)).fetchall()]
            for sid in ids:
                conn.execute("DELETE FROM strength_sets WHERE session_id=?", (sid,))
                conn.execute("DELETE FROM strength_sessions WHERE id=?", (sid,))
        for line, entry in entries:
            if entry["logged_at"] in superseded:
                continue  # this original was corrected by a later entry
            h = hashlib.sha256(line.encode()).hexdigest()
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
