"""
Pure string templates -- no database, no network. These assertions
check for the substantive content (name, date, time, key phrases), not
exact wording, so a tone tweak doesn't break the test suite for no
reason -- but a missing date/time/name WOULD be a real bug worth catching.
"""
import sms_templates as t


def test_appointment_reminder_includes_all_details():
    msg = t.appointment_reminder("Maria", "Dr. Lee", "Friday, Aug 28", "9:30 AM")
    assert "Maria" in msg
    assert "Dr. Lee" in msg
    assert "Friday, Aug 28" in msg
    assert "9:30 AM" in msg
    assert "RESCHEDULE" in msg


def test_confirmation_ack_includes_date_and_time():
    msg = t.confirmation_ack("Friday, Aug 28", "9:30 AM")
    assert "Friday, Aug 28" in msg and "9:30 AM" in msg


def test_reschedule_slot_offer_lists_all_options():
    msg = t.reschedule_slot_offer("Dr. Lee", ["1) Mon 9am", "2) Mon 10am", "3) Tue 9am"])
    assert "Dr. Lee" in msg
    for option in ("1) Mon 9am", "2) Mon 10am", "3) Tue 9am"):
        assert option in msg


def test_reschedule_confirmed_includes_details():
    msg = t.reschedule_confirmed("Dr. Patel", "Monday, Sep 1", "10:00 AM")
    assert "Dr. Patel" in msg and "Monday, Sep 1" in msg and "10:00 AM" in msg


def test_new_appointment_offer_lists_options():
    msg = t.new_appointment_offer("Dr. Lee", ["1) Fri 9am"])
    assert "Dr. Lee" in msg and "1) Fri 9am" in msg


def test_new_appointment_confirmed_includes_details():
    msg = t.new_appointment_confirmed("Dr. Lee", "Friday, Aug 28", "9:00 AM")
    assert "Dr. Lee" in msg and "Friday, Aug 28" in msg and "9:00 AM" in msg


def test_missed_call_followup_includes_name():
    msg = t.missed_call_followup("James")
    assert "James" in msg


def test_verification_prompt_asks_for_dob():
    assert "date of birth" in t.verification_prompt().lower()


def test_verification_retry_is_gentle_not_accusatory():
    msg = t.verification_retry().lower()
    assert "doesn't match" in msg
    assert "wrong" not in msg  # tone check -- never blame the patient


def test_verification_unparseable_asks_for_format():
    assert "MM/DD/YYYY" in t.verification_unparseable()


def test_verification_escalate_includes_next_available_time():
    msg = t.verification_escalate("tomorrow morning at 8am")
    assert "tomorrow morning at 8am" in msg


def test_no_account_found_mentions_calling_office():
    assert "call" in t.no_account_found().lower()


def test_nothing_to_confirm_is_informative():
    assert "nothing" in t.nothing_to_confirm().lower()


def test_nothing_to_reschedule_offers_alternative():
    assert "book a new one" in t.nothing_to_reschedule().lower()


def test_fully_booked_that_day_includes_provider_and_next_available():
    msg = t.fully_booked_that_day("Dr. Lee", "Monday morning at 8am")
    assert "Dr. Lee" in msg and "Monday morning at 8am" in msg


def test_system_trouble_never_leaks_internal_error_detail():
    """This message is shown when a real exception happened -- it must
    never be handed the exception text itself, only a next-available
    phrase, so patients never see a stack trace or SQL error."""
    msg = t.system_trouble("tomorrow morning at 8am")
    assert "tomorrow morning at 8am" in msg
    assert "Error" not in msg
    assert "Traceback" not in msg


def test_ai_disclosure_footer_names_the_assistant():
    assert "Moty" in t.ai_disclosure_footer()


def test_practice_name_constant_used_in_reminder():
    assert t.PRACTICE_NAME in t.appointment_reminder("Maria", "Dr. Lee", "Friday", "9am")
