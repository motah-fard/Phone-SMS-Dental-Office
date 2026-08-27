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
