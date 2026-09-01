"""
integrations/sms_conversation.py -- the deterministic SMS state machine.
The LLM fallback path is monkeypatched to a fake function in the one
test that exercises it, so this suite never makes a real API call or
needs a real API key.
"""
from datetime import datetime, timedelta

import sms_conversation as sc


# --- YES: confirming an existing appointment, no verification needed ---

def test_yes_unknown_number_says_no_account_found(fresh_db):
    reply, state = sc.handle_inbound_sms("+19995550000", "YES", {})
    assert "couldn't find an account" in reply


def test_yes_confirms_existing_appointment(fresh_db):
    reply, state = sc.handle_inbound_sms("+15551230001", "YES", {})
    assert "confirmed" in reply.lower()


def test_yes_lowercase_still_matches(fresh_db):
    reply, state = sc.handle_inbound_sms("+15551230001", "yes", {})
    assert "confirmed" in reply.lower()


def test_yes_nothing_to_confirm_when_no_appointments(fresh_db):
    import sqlite3
    from book import MIRROR_DB
    conn = sqlite3.connect(MIRROR_DB)
    conn.execute("UPDATE appointments SET status = 'cancelled' WHERE patient_id = 'PT-0001'")
    conn.commit()
    conn.close()

    reply, state = sc.handle_inbound_sms("+15551230001", "YES", {})
    assert "nothing on the books" in reply.lower()


# --- Rollout stage gate (checked before verification even starts) ---

def test_reschedule_blocked_when_stage_is_confirmations_only(fresh_db, monkeypatch):
    monkeypatch.setattr(sc.rollout_stage, "ROLLOUT_STAGE", "confirmations_only")
    reply, state = sc.handle_inbound_sms("+15551230001", "RESCHEDULE", {})
    assert "date of birth" not in reply.lower()  # never even gets to asking
    assert "pending_verification_for" not in state


def test_book_blocked_unless_stage_is_full(fresh_db, monkeypatch):
    monkeypatch.setattr(sc.rollout_stage, "ROLLOUT_STAGE", "reschedule")
    reply, state = sc.handle_inbound_sms("+15551230003", "BOOK", {})
    assert "date of birth" not in reply.lower()
    assert "pending_verification_for" not in state


# --- RESCHEDULE: requires verification first ---

def test_reschedule_first_message_asks_for_dob(fresh_db):
    reply, state = sc.handle_inbound_sms("+15551230001", "RESCHEDULE", {})
    assert "date of birth" in reply.lower()
    assert state["pending_verification_for"] == "reschedule"


def test_reschedule_unparseable_dob_asks_again_without_counting_as_failed_attempt(fresh_db):
    state = {"pending_verification_for": "reschedule"}
    reply, state = sc.handle_inbound_sms("+15551230001", "not a date", state)
    assert "MM/DD/YYYY" in reply
    assert state.get("failed_verification_attempts", 0) == 0


def test_reschedule_wrong_dob_once_asks_to_double_check(fresh_db):
    state = {"pending_verification_for": "reschedule"}
    reply, state = sc.handle_inbound_sms("+15551230001", "01/01/1999", state)
    assert "doesn't match" in reply.lower()
    assert state["failed_verification_attempts"] == 1
    assert state["pending_verification_for"] == "reschedule"  # still pending, gets another try


def test_reschedule_wrong_dob_twice_escalates(fresh_db):
    state = {"pending_verification_for": "reschedule"}
    _, state = sc.handle_inbound_sms("+15551230001", "01/01/1999", state)
    reply, state = sc.handle_inbound_sms("+15551230001", "01/01/1999", state)
    assert "front desk" in reply.lower()
    assert "pending_verification_for" not in state


def test_reschedule_correct_dob_offers_slots(fresh_db):
    state = {"pending_verification_for": "reschedule"}
    reply, state = sc.handle_inbound_sms("+15551230001", "04/12/1988", state)
    assert "reply with the one" in reply.lower()
    assert len(state["offered_slots"]) > 0
    assert state["offered_slots"][0]["mode"] == "reschedule"
    assert state["verified_patient"]["patient_id"] == "PT-0001"


def test_reschedule_already_verified_skips_dob_prompt(fresh_db):
    state = {"verified_patient": {"patient_id": "PT-0001", "first_name": "Maria", "source_patient_id": 1}}
    reply, state = sc.handle_inbound_sms("+15551230001", "RESCHEDULE", state)
    assert "date of birth" not in reply.lower()
    assert len(state["offered_slots"]) > 0


def test_reschedule_nothing_to_reschedule_when_no_appointment(fresh_db):
    from book import MIRROR_DB
    import sqlite3
    conn = sqlite3.connect(MIRROR_DB)
    conn.execute("UPDATE appointments SET status = 'cancelled' WHERE patient_id = 'PT-0001'")
    conn.commit()
    conn.close()

    state = {"verified_patient": {"patient_id": "PT-0001", "first_name": "Maria", "source_patient_id": 1}}
    reply, state = sc.handle_inbound_sms("+15551230001", "RESCHEDULE", state)
    assert "book a new one" in reply.lower()


def test_reschedule_fully_booked_within_search_window(fresh_db, monkeypatch):
    monkeypatch.setattr(sc, "find_soonest_slots", lambda *a, **k: [])
    state = {"verified_patient": {"patient_id": "PT-0001", "first_name": "Maria", "source_patient_id": 1}}
    reply, state = sc.handle_inbound_sms("+15551230001", "RESCHEDULE", state)
    assert "fully booked" in reply.lower()


def test_book_new_appointment_fully_booked_within_search_window(fresh_db, monkeypatch):
    monkeypatch.setattr(sc, "find_soonest_slots_any_provider", lambda *a, **k: (None, []))
    state = {"verified_patient": {"patient_id": "PT-0003", "first_name": "Aiko", "source_patient_id": 3}}
    reply, state = sc.handle_inbound_sms("+15551230003", "BOOK", state)
    assert "fully booked" in reply.lower()


def test_book_already_verified_skips_dob_prompt(fresh_db):
    state = {"verified_patient": {"patient_id": "PT-0003", "first_name": "Aiko", "source_patient_id": 3}}
    reply, state = sc.handle_inbound_sms("+15551230003", "BOOK", state)
    assert "date of birth" not in reply.lower()
    assert len(state["offered_slots"]) > 0
    assert state["offered_slots"][0]["mode"] == "book"


# --- BOOK: new appointment, same verification policy ---

def test_book_keyword_triggers_verification_prompt(fresh_db):
    reply, state = sc.handle_inbound_sms("+15551230003", "I want to book something", {})
    assert "date of birth" in reply.lower()
    assert state["pending_verification_for"] == "book"


def test_book_correct_dob_offers_new_slots(fresh_db):
    state = {"pending_verification_for": "book"}
    reply, state = sc.handle_inbound_sms("+15551230003", "07/23/1992", state)
    assert "soonest we've got" in reply.lower()
    assert state["offered_slots"][0]["mode"] == "book"


# --- Picking an offered slot ---

def test_picking_slot_1_for_reschedule_confirms_and_writes_back(fresh_db):
    state = {"pending_verification_for": "reschedule"}
    _, state = sc.handle_inbound_sms("+15551230001", "04/12/1988", state)
    reply, state = sc.handle_inbound_sms("+15551230001", "1", state)
    assert "all set" in reply.lower()
    assert "offered_slots" not in state


def test_picking_slot_for_book_confirms_and_creates_new_appointment(fresh_db):
    state = {"pending_verification_for": "book"}
    _, state = sc.handle_inbound_sms("+15551230003", "07/23/1992", state)
    reply, state = sc.handle_inbound_sms("+15551230003", "1", state)
    assert "all booked" in reply.lower()


def test_picking_a_number_with_no_offered_slots_falls_through_to_llm(fresh_db, monkeypatch):
    called = {}

    def fake_llm(phone, text, state):
        called["args"] = (phone, text)
        return "handled by fake llm", state

    monkeypatch.setattr(sc, "handle_open_ended", fake_llm)
    reply, state = sc.handle_inbound_sms("+15551230001", "1", {})
    assert reply == "handled by fake llm"
    assert called["args"] == ("+15551230001", "1")


# --- Open-ended fallback boundary ---

def test_open_ended_text_is_handed_to_llm_fallback(fresh_db, monkeypatch):
    def fake_llm(phone, text, state):
        return f"fake reply to: {text}", state

    monkeypatch.setattr(sc, "handle_open_ended", fake_llm)
    reply, state = sc.handle_inbound_sms("+15551230001", "can I bring my kid too?", {})
    assert reply == "fake reply to: can I bring my kid too?"


# --- Outer error handling never crashes ---

def test_scheduling_error_becomes_calm_message_not_a_crash(fresh_db, monkeypatch):
    def boom(*args, **kwargs):
        raise sc.SchedulingError("simulated db outage")

    monkeypatch.setattr(sc, "resolve_patient_by_phone", boom)
    reply, state = sc.handle_inbound_sms("+15551230001", "YES", {})
    assert "trouble" in reply.lower()
    assert "simulated db outage" not in reply  # never leak the raw error


def test_state_is_never_mutated_in_place(fresh_db):
    """handle_inbound_sms must return a new dict, not mutate the caller's
    -- webhook_server.py relies on this to store state per-phone safely."""
    original_state = {"some_key": "some_value"}
    sc.handle_inbound_sms("+15551230001", "YES", original_state)
    assert original_state == {"some_key": "some_value"}
