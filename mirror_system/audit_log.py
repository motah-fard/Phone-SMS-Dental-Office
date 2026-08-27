"""
Append-only access log for anything that touches patient data. HIPAA
requires audit controls showing who/what accessed a record and when --
this is that.

Deliberately logs by pseudonymous patient_id, not name or phone, to stay
consistent with the rest of this system's design (identity_lookup.db is
the only place real identity lives). The one exception is a failed
identity lookup, where there's no patient_id yet -- that logs only the
last 4 digits of the phone number, enough to debug without storing the
full number.

This file (audit_log.db) is itself sensitive -- it's a record of who
accessed which patient's data and when -- and needs the same protection
as identity_lookup.db once this is deployed for real (encryption at
rest, restricted access), not just because it's convenient to keep
separate from mirror.db.

To add logging for a new action: call log_access(...) at the point the
action happens. Don't create a second logging module -- one place to
fix if the logging format ever needs to change.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

AUDIT_DB = Path(__file__).parent / "audit_log.db"


def _ensure_table(conn: sqlite3.Connection):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS access_log (
            id INTEGER PRIMARY KEY,
            timestamp TEXT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            patient_id TEXT,
            detail TEXT,
            success INTEGER NOT NULL
        )
        """
    )


def log_access(actor: str, action: str, patient_id: str | None = None, detail: str = "", success: bool = True):
    """actor: which part of the system did this, e.g. 'sms_webhook',
    'voice_tool:reschedule_appointment', 'sync_job'. Kept as a free-form
    string on purpose -- new channels don't require a schema change."""
    conn = sqlite3.connect(AUDIT_DB)
    _ensure_table(conn)
    conn.execute(
        "INSERT INTO access_log (timestamp, actor, action, patient_id, detail, success) VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), actor, action, patient_id, detail, int(success)),
    )
    conn.commit()
    conn.close()


def read_recent(limit: int = 50):
    conn = sqlite3.connect(AUDIT_DB)
    _ensure_table(conn)
    cur = conn.execute(
        "SELECT timestamp, actor, action, patient_id, detail, success "
        "FROM access_log ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows
