"""mirror_system/audit_log.py -- the HIPAA access-log module."""
import audit_log


def test_log_access_and_read_recent_round_trip(fresh_db):
    audit_log.log_access("test_actor", "test_action", patient_id="PT-0001", detail="hello")
    rows = audit_log.read_recent(limit=1)
    assert len(rows) == 1
    timestamp, actor, action, patient_id, detail, success = rows[0]
    assert actor == "test_actor"
    assert action == "test_action"
    assert patient_id == "PT-0001"
    assert detail == "hello"
    assert success == 1


def test_log_access_defaults_to_success_true(fresh_db):
    audit_log.log_access("test_actor", "some_action")
    rows = audit_log.read_recent(limit=1)
    assert rows[0][5] == 1


def test_log_access_records_failure(fresh_db):
    audit_log.log_access("test_actor", "failed_action", success=False, detail="bad phone")
    rows = audit_log.read_recent(limit=1)
    assert rows[0][5] == 0
    assert rows[0][4] == "bad phone"


def test_log_access_patient_id_optional(fresh_db):
    audit_log.log_access("test_actor", "no_patient_action")
    rows = audit_log.read_recent(limit=1)
    assert rows[0][3] is None


def test_read_recent_returns_newest_first(fresh_db):
    audit_log.log_access("actor", "first_action")
    audit_log.log_access("actor", "second_action")
    rows = audit_log.read_recent(limit=2)
    assert rows[0][2] == "second_action"
    assert rows[1][2] == "first_action"


def test_read_recent_respects_limit(fresh_db):
    for i in range(5):
        audit_log.log_access("actor", f"action_{i}")
    rows = audit_log.read_recent(limit=3)
    assert len(rows) == 3


def test_read_recent_on_empty_log_returns_empty_list(fresh_db):
    assert audit_log.read_recent() == []


def test_log_llm_call_and_read_recent_round_trip(fresh_db):
    audit_log.log_llm_call(
        actor="sms_llm_fallback", provider="anthropic", model="claude-sonnet-5",
        latency_ms=123.4, input_tokens=500, output_tokens=50, estimated_cost_usd=0.0015,
    )
    rows = audit_log.read_recent_llm_calls(limit=1)
    assert len(rows) == 1
    timestamp, actor, provider, model, latency_ms, input_tokens, output_tokens, cost = rows[0]
    assert actor == "sms_llm_fallback"
    assert provider == "anthropic"
    assert model == "claude-sonnet-5"
    assert latency_ms == 123.4
    assert input_tokens == 500
    assert output_tokens == 50
    assert cost == 0.0015


def test_log_llm_call_allows_missing_token_counts(fresh_db):
    """Some responses (e.g. an error before usage is known) might not
    have token counts -- these must stay optional, not required."""
    audit_log.log_llm_call(actor="test", provider="anthropic", model="claude-sonnet-5", latency_ms=50.0)
    rows = audit_log.read_recent_llm_calls(limit=1)
    assert rows[0][5] is None and rows[0][6] is None and rows[0][7] is None


def test_read_recent_llm_calls_newest_first_and_respects_limit(fresh_db):
    for i in range(5):
        audit_log.log_llm_call(actor="test", provider="anthropic", model="claude-sonnet-5", latency_ms=float(i))
    rows = audit_log.read_recent_llm_calls(limit=3)
    assert len(rows) == 3
    assert rows[0][4] == 4.0  # latency_ms of the most recent call


def test_read_recent_llm_calls_on_empty_log_returns_empty_list(fresh_db):
    assert audit_log.read_recent_llm_calls() == []
