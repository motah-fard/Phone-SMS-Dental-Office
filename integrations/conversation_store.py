"""
Persistent, cross-process conversation state -- replaces the earlier
in-memory dict in webhook_server.py, which reset on every restart and
wouldn't work with more than one server process (a real WSGI server
like waitress can run several worker processes).

Known limitation, deliberate: `llm_history` is NOT persisted. Anthropic
and OpenAI's SDK response objects (tool_use/tool_call blocks) aren't
cleanly JSON-serializable, and solving that properly is more machinery
than the actual risk justifies -- if the server restarts mid-LLM-
conversation, that specific open-ended back-and-forth loses its recent
context and the next message starts a fresh one. What DOES persist is
everything that actually matters for correctness/security:
verified_patient, offered_slots, pending_verification_for, and the
failed-attempt counter -- so a restart can't cause someone to lose
their verification, get double-booked, or bypass a verification retry
limit. That's the real bar; perfect LLM memory across a restart isn't.
"""
import json
import sqlite3
import time
from pathlib import Path

STATE_DB = Path(__file__).parent.parent / "mirror_system" / "conversation_state.db"
TTL_SECONDS = 30 * 60  # 30 min of inactivity -- long enough for a real back-and-forth text exchange, short enough not to accumulate indefinitely

_NOT_PERSISTED_KEYS = {"llm_history"}


def _ensure_table(conn: sqlite3.Connection):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_state (
            phone TEXT PRIMARY KEY,
            state_json TEXT NOT NULL,
            last_touched REAL NOT NULL
        )
        """
    )


def _sweep_expired(conn: sqlite3.Connection):
    conn.execute("DELETE FROM conversation_state WHERE last_touched < ?", (time.time() - TTL_SECONDS,))


def get_state(phone: str) -> dict:
    """Sweeps expired rows on every access -- no background thread
    needed at this scale, and storage never grows purely from time
    passing, only from genuinely active conversations."""
    conn = sqlite3.connect(STATE_DB)
    _ensure_table(conn)
    _sweep_expired(conn)
    conn.commit()
    row = conn.execute("SELECT state_json FROM conversation_state WHERE phone = ?", (phone,)).fetchone()
    conn.close()
    return json.loads(row[0]) if row else {}


def set_state(phone: str, state: dict):
    persistable = {k: v for k, v in state.items() if k not in _NOT_PERSISTED_KEYS}
    conn = sqlite3.connect(STATE_DB)
    _ensure_table(conn)
    conn.execute(
        """
        INSERT INTO conversation_state (phone, state_json, last_touched) VALUES (?, ?, ?)
        ON CONFLICT(phone) DO UPDATE SET state_json = excluded.state_json, last_touched = excluded.last_touched
        """,
        (phone, json.dumps(persistable), time.time()),
    )
    conn.commit()
    conn.close()
