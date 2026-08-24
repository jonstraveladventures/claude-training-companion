import hashlib
import json
import sys
from pathlib import Path

from .db import connect

LOG_PATH = Path(__file__).resolve().parents[2] / "data" / "strength_log.jsonl"


def ingest() -> int:
    if not LOG_PATH.exists():
        return 0
    # Skip (and warn about) a malformed line rather than crashing the whole
    # ingest — a bad hand-appended line must not take down every builder.
    entries = []
    for n, ln in enumerate(LOG_PATH.read_text().splitlines(), 1):
        l = ln.strip()
        if not l:
            continue
        try:
            entries.append((l, json.loads(l)))
        except json.JSONDecodeError as e:
            print(f"WARN strength_log.jsonl:{n} skipped malformed line: {e}",
                  file=sys.stderr)
    # correction_of supersession: a later entry with correction_of=<logged_at>
    # replaces that original, which must NOT live in the DB or it double-counts.
    # The two committed builders already honour this; ingest() must too.
    superseded = {e.get("correction_of") for _, e in entries if e.get("correction_of")}
    inserted = 0
    live_hashes = {hashlib.sha256(line.encode()).hexdigest() for line, _ in entries}
    with connect() as conn:
        # Purge ORPHANS: sessions whose source line no longer exists verbatim.
        # Dedup is by SHA of the raw line, so editing a line in place (which the
        # logging protocol allows for a fresh, uncommitted typo) yields a NEW
        # hash — the edited line then inserts as a SECOND session while the
        # pre-edit one lingers, silently double-counting that date in every
        # DB-based analysis. Anything whose hash is gone from the file is stale
        # by definition, so drop it before inserting.
        if live_hashes:
            ph = ",".join("?" * len(live_hashes))
            stale = [r[0] for r in conn.execute(
                f"SELECT id FROM strength_sessions WHERE source_line_hash NOT IN ({ph})",
                tuple(live_hashes)).fetchall()]
            for sid in stale:
                conn.execute("DELETE FROM strength_sets WHERE session_id=?", (sid,))
                conn.execute("DELETE FROM strength_sessions WHERE id=?", (sid,))
            if stale:
                print(f"  purged {len(stale)} stale session(s) whose log line changed or vanished")
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
