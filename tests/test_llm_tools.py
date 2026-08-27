"""integrations/llm_tools.py -- the tool executor shared by both LLM
providers, tested directly rather than only through the tool-call loops."""
from datetime import datetime, timedelta

import llm_tools as lt


def test_verify_patient_tool_success_populates_session(fresh_db):
    session = {}
    result = lt.execute_tool("verify_patient", {"dob": "04/12/1988"}, "+15551230001", session)
    assert result["verified"] is True
    assert result["first_name"] == "Maria"
    assert session["verified_patient"]["patient_id"] == "PT-0001"


def test_verify_patient_tool_wrong_dob_does_not_populate_session(fresh_db):
    session = {}
    result = lt.execute_tool("verify_patient", {"dob": "01/01/1999"}, "+15551230001", session)
    assert result["verified"] is False
    assert "verified_patient" not in session


def test_verify_patient_tool_unparseable_dob(fresh_db):
    result = lt.execute_tool("verify_patient", {"dob": "garbage"}, "+15551230001", {})
    assert result["verified"] is False
    assert "error" in result


def test_get_upcoming_appointments_tool_requires_verification_first(fresh_db):
    result = lt.execute_tool("get_upcoming_appointments", {}, "+15551230001", {})
    assert "error" in result


def test_get_upcoming_appointments_tool_after_verification(fresh_db):
    session = {}
    lt.execute_tool("verify_patient", {"dob": "04/12/1988"}, "+15551230001", session)
    result = lt.execute_tool("get_upcoming_appointments", {}, "+15551230001", session)
    assert len(result["appointments"]) == 1


def test_check_availability_tool_does_not_require_verification(fresh_db):
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    result = lt.execute_tool("check_availability", {"provider_id": 1, "day": tomorrow}, "+15551230001", {})
    assert "slots" in result


def test_reschedule_appointment_tool_requires_verification(fresh_db):
    result = lt.execute_tool(
        "reschedule_appointment",
        {"appointment_id": 1, "new_start": datetime.now().isoformat(), "new_end": datetime.now().isoformat()},
        "+15551230001", {},
    )
    assert "error" in result


def test_reschedule_appointment_tool_after_verification(fresh_db):
    session = {}
    lt.execute_tool("verify_patient", {"dob": "04/12/1988"}, "+15551230001", session)
    new_start = datetime.now() + timedelta(days=3)
    new_end = new_start + timedelta(minutes=30)
    result = lt.execute_tool(
        "reschedule_appointment",
        {"appointment_id": 1, "new_start": new_start.isoformat(), "new_end": new_end.isoformat()},
        "+15551230001", session,
    )
    assert result["status"] == "rescheduled"


def test_find_new_appointment_slots_tool_requires_verification(fresh_db):
    result = lt.execute_tool("find_new_appointment_slots", {}, "+15551230003", {})
    assert "error" in result


def test_find_new_appointment_slots_tool_after_verification(fresh_db):
    session = {}
    lt.execute_tool("verify_patient", {"dob": "07/23/1992"}, "+15551230003", session)
    result = lt.execute_tool("find_new_appointment_slots", {}, "+15551230003", session)
    assert result["provider"] is not None
    assert len(result["slots"]) > 0


def test_find_new_appointment_slots_tool_none_available(fresh_db, monkeypatch):
    monkeypatch.setattr(lt, "find_soonest_slots_any_provider", lambda *a, **k: (None, []))
    session = {"verified_patient": {"patient_id": "PT-0003", "first_name": "Aiko", "source_patient_id": 3}}
    result = lt.execute_tool("find_new_appointment_slots", {}, "+15551230003", session)
    assert result == {"slots": [], "provider": None}


def test_book_new_appointment_tool_requires_verification(fresh_db):
    result = lt.execute_tool(
        "book_new_appointment",
        {"provider_id": 1, "new_start": datetime.now().isoformat(), "new_end": datetime.now().isoformat()},
        "+15551230003", {},
    )
    assert "error" in result


def test_book_new_appointment_tool_after_verification(fresh_db):
    session = {}
    lt.execute_tool("verify_patient", {"dob": "07/23/1992"}, "+15551230003", session)
    start = datetime.now() + timedelta(days=5)
    end = start + timedelta(minutes=30)
    result = lt.execute_tool(
        "book_new_appointment",
        {"provider_id": 1, "new_start": start.isoformat(), "new_end": end.isoformat()},
        "+15551230003", session,
    )
    assert result["status"] == "booked"
    assert "appointment_id" in result


def test_check_staffed_hours_tool_returns_expected_shape(fresh_db):
    result = lt.execute_tool("check_staffed_hours", {}, "+15551230001", {})
    assert "staffed" in result
    assert "next_available" in result


def test_unknown_tool_name_returns_error_not_exception(fresh_db):
    result = lt.execute_tool("delete_all_patients", {}, "+15551230001", {})
    assert "error" in result


def test_execute_tool_catches_scheduling_error_and_returns_dict(fresh_db, monkeypatch):
    """A real backend failure inside a tool must come back as an error
    dict the model can react to, never propagate as a raw exception --
    the LLM's tool loop has no other way to recover mid-conversation."""
    def boom(*args, **kwargs):
        raise lt.SchedulingError("simulated failure")

    monkeypatch.setattr(lt, "get_upcoming_appointments", boom)
    session = {"verified_patient": {"patient_id": "PT-0001", "first_name": "Maria", "source_patient_id": 1}}
    result = lt.execute_tool("get_upcoming_appointments", {}, "+15551230001", session)
    assert "error" in result
    assert "simulated failure" not in result["error"]  # never leak the raw exception text


def test_phone_from_tool_input_is_ignored_verify_patient(fresh_db):
    """Even if tool_input somehow contained a phone field, execute_tool
    must use the `phone` argument passed in by the caller, never
    anything from tool_input -- verify_patient has no `phone` in its own
    schema, but this guards against a future tool accidentally adding one."""
    session = {}
    result = lt.execute_tool(
        "verify_patient", {"dob": "04/12/1988", "phone": "+19995551234"}, "+15551230001", session,
    )
    assert result["verified"] is True
    assert session["verified_patient"]["patient_id"] == "PT-0001"  # matches the real phone, not the fake one
