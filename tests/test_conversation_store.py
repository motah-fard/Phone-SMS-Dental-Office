"""integrations/conversation_store.py -- the persistent, cross-process
replacement for the old in-memory conversation state dict."""
import conversation_store as cs


def test_get_state_missing_phone_returns_empty_dict(fresh_db):
    assert cs.get_state("+19995550000") == {}


def test_set_then_get_round_trips(fresh_db):
    cs.set_state("+15551230001", {"some_key": "some_value"})
    assert cs.get_state("+15551230001") == {"some_key": "some_value"}


def test_set_state_overwrites_previous_value(fresh_db):
    cs.set_state("+15551230001", {"a": 1})
    cs.set_state("+15551230001", {"a": 2})
    assert cs.get_state("+15551230001") == {"a": 2}


def test_llm_history_is_never_persisted(fresh_db):
    """Documented, deliberate limitation -- Anthropic/OpenAI SDK content
    blocks in llm_history aren't cleanly JSON-serializable, so they're
    dropped rather than crashing the whole state save."""
    cs.set_state("+15551230001", {"verified_patient": {"patient_id": "PT-0001"}, "llm_history": [object()]})
    state = cs.get_state("+15551230001")
    assert "llm_history" not in state
    assert state["verified_patient"] == {"patient_id": "PT-0001"}


def test_state_expires_after_ttl(monkeypatch):
    import sqlite3
    cs.set_state("+15551230001", {"a": 1})
    # Simulate time passing without actually sleeping.
    conn = sqlite3.connect(cs.STATE_DB)
    conn.execute("UPDATE conversation_state SET last_touched = last_touched - ? WHERE phone = ?",
                 (cs.TTL_SECONDS + 1, "+15551230001"))
    conn.commit()
    conn.close()

    assert cs.get_state("+15551230001") == {}  # swept, not just ignored


def test_sweep_does_not_remove_fresh_entries():
    import sqlite3
    cs.set_state("+15551230001", {"a": 1})
    cs.set_state("+15551230002", {"b": 2})
    conn = sqlite3.connect(cs.STATE_DB)
    conn.execute("UPDATE conversation_state SET last_touched = last_touched - ? WHERE phone = ?",
                 (cs.TTL_SECONDS + 1, "+15551230001"))
    conn.commit()
    conn.close()

    assert cs.get_state("+15551230001") == {}
    assert cs.get_state("+15551230002") == {"b": 2}  # untouched, stays available
