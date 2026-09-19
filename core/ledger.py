"""AJOS ledger: SQLite source of truth. State machine + append-only events + chunk_stats.

Design rule: state lives here, workers are stateless. Every module reads/writes
through this file. The events table is the loop's bloodstream — the weekly
Reflection pass (slow loop) reads it to learn.
"""
import json
import sqlite3
import time
from pathlib import Path

AJOS_DIR = Path(__file__).resolve().parent.parent

# Enforced state machine. Key = from-state, value = allowed to-states.
TRANSITIONS = {
    "discovered": ["normalized", "dropped", "rejected_workauth", "needs_manual"],
    "normalized": ["routed", "dropped", "rejected_workauth", "needs_manual"],
    "routed": ["evidence_ready", "dropped", "needs_manual"],
    "evidence_ready": ["tailoring", "dropped", "needs_manual"],
    "tailoring": ["tailored", "dropped", "needs_manual"],
    "tailored": ["qa_passed", "qa_failed", "needs_manual"],
    "qa_failed": ["tailoring", "needs_manual", "dropped"],
    "qa_passed": ["staged", "needs_manual"],
    "staged": ["submitted", "dropped", "needs_manual"],
    "submitted": ["outcome_rejected", "outcome_callback", "outcome_interview",
                  "outcome_offer", "outcome_ghosted"],
    "needs_manual": ["normalized", "routed", "evidence_ready", "tailoring",
                     "tailored", "qa_passed", "staged", "dropped"],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    app_id TEXT PRIMARY KEY,
    company TEXT, role_title TEXT, location TEXT, url TEXT, ats TEXT,
    bucket TEXT, base_used TEXT, route_similarity REAL,
    status TEXT NOT NULL DEFAULT 'discovered',
    qa_retries INTEGER DEFAULT 0,
    work_auth_ok INTEGER, jd_path TEXT, app_dir TEXT,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, app_id TEXT, actor TEXT NOT NULL,
    event TEXT NOT NULL, detail TEXT
);
CREATE TABLE IF NOT EXISTS chunk_stats (
    chunk_id TEXT PRIMARY KEY,
    section TEXT, text_head TEXT,
    times_retrieved INTEGER DEFAULT 0,
    times_used INTEGER DEFAULT 0,
    times_in_callback INTEGER DEFAULT 0,
    last_retrieved TEXT
);
CREATE TABLE IF NOT EXISTS playbook_rules (
    rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT, source TEXT, rule TEXT,
    status TEXT DEFAULT 'proposed'  -- proposed | approved | rejected | reverted
);
"""


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open the ledger. If the configured path is on a filesystem SQLite can't
    lock (cloud-sync mounts), fall back to ~/.ajos/ledger.sqlite and warn.
    Portability is preserved by export_json() after every CLI command."""
    import os
    path = Path(os.environ.get("AJOS_DB") or db_path or AJOS_DIR / "ledger.sqlite")
    for candidate in (path, Path.home() / ".ajos" / "ledger.sqlite"):
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(candidate)
            con.row_factory = sqlite3.Row
            con.executescript(SCHEMA)
            if candidate != path:
                print(f"[ledger] WARNING: {path} not writable by sqlite; using {candidate}")
            return con
        except sqlite3.OperationalError:
            continue
    raise sqlite3.OperationalError("no writable location for ledger.sqlite")


def export_json(con, out_path: Path):
    """Portable snapshot of the ledger into the synced folder — the file any
    model reads to resume, and the dashboard's data source."""
    dump = {
        "exported_at": now(),
        "applications": [dict(r) for r in con.execute(
            "SELECT * FROM applications ORDER BY updated_at DESC")],
        "events": [dict(r) for r in con.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT 500")],
        "chunk_stats": [dict(r) for r in con.execute(
            "SELECT * FROM chunk_stats ORDER BY times_retrieved DESC LIMIT 200")],
        "playbook_rules": [dict(r) for r in con.execute(
            "SELECT * FROM playbook_rules ORDER BY rule_id DESC LIMIT 200")],
    }
    out_path.write_text(json.dumps(dump, indent=2))


def log_event(con, app_id, actor, event, detail=None):
    con.execute(
        "INSERT INTO events (ts, app_id, actor, event, detail) VALUES (?,?,?,?,?)",
        (now(), app_id, actor,
         event, json.dumps(detail) if isinstance(detail, (dict, list)) else detail),
    )
    con.commit()


def create_application(con, app_id, **fields) -> bool:
    """Insert a new application. Returns False if it's a duplicate (the guard)."""
    dup = con.execute(
        "SELECT app_id FROM applications WHERE app_id=?", (app_id,)
    ).fetchone()
    if dup:
        log_event(con, app_id, "ledger", "duplicate_blocked",
                  "app_id already in ledger — duplicate-application guard")
        return False
    cols = ["app_id", "status", "created_at", "updated_at"] + list(fields)
    vals = [app_id, "discovered", now(), now()] + list(fields.values())
    con.execute(
        f"INSERT INTO applications ({','.join(cols)}) VALUES ({','.join('?' * len(vals))})",
        vals,
    )
    log_event(con, app_id, "ledger", "created", fields)
    return True


def similar_company_recent(con, company, days=90):
    """Second layer of the dup guard: same company within N days."""
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - days * 86400))
    return con.execute(
        "SELECT app_id, role_title, status, created_at FROM applications "
        "WHERE lower(company)=lower(?) AND created_at > ?",
        (company, cutoff),
    ).fetchall()


def transition(con, app_id, to_status, actor, note=None, qa_retry_limit=2):
    row = con.execute(
        "SELECT status, qa_retries FROM applications WHERE app_id=?", (app_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown app_id {app_id}")
    frm = row["status"]
    allowed = TRANSITIONS.get(frm, [])
    if to_status not in allowed:
        log_event(con, app_id, actor, "transition_blocked",
                  f"{frm} -> {to_status} not allowed (allowed: {allowed})")
        raise ValueError(f"illegal transition {frm} -> {to_status}")
    if to_status == "tailoring" and frm == "qa_failed":
        if row["qa_retries"] >= qa_retry_limit:
            to_status = "needs_manual"
            note = f"qa retry limit reached ({qa_retry_limit}). {note or ''}"
        else:
            con.execute("UPDATE applications SET qa_retries=qa_retries+1 WHERE app_id=?",
                        (app_id,))
    con.execute("UPDATE applications SET status=?, updated_at=? WHERE app_id=?",
                (to_status, now(), app_id))
    log_event(con, app_id, actor, "transition", f"{frm} -> {to_status}" + (f" | {note}" if note else ""))
    return to_status


def set_fields(con, app_id, **fields):
    sets = ",".join(f"{k}=?" for k in fields)
    con.execute(f"UPDATE applications SET {sets}, updated_at=? WHERE app_id=?",
                list(fields.values()) + [now(), app_id])
    con.commit()


def record_retrieval(con, chunks):
    """chunks: list of dicts with chunk_id, section, text_head."""
    for c in chunks:
        con.execute(
            "INSERT INTO chunk_stats (chunk_id, section, text_head, times_retrieved, last_retrieved) "
            "VALUES (?,?,?,1,?) ON CONFLICT(chunk_id) DO UPDATE SET "
            "times_retrieved=times_retrieved+1, last_retrieved=excluded.last_retrieved",
            (c["chunk_id"], c["section"], c["text_head"][:120], now()),
        )
    con.commit()


def record_usage(con, chunk_ids):
    for cid in chunk_ids:
        con.execute("UPDATE chunk_stats SET times_used=times_used+1 WHERE chunk_id=?", (cid,))
    con.commit()


def get_application(con, app_id):
    return con.execute("SELECT * FROM applications WHERE app_id=?", (app_id,)).fetchone()


def list_applications(con):
    return con.execute(
        "SELECT app_id, company, role_title, bucket, status, route_similarity, updated_at "
        "FROM applications ORDER BY updated_at DESC"
    ).fetchall()
