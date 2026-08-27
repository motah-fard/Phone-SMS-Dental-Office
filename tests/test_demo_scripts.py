"""
The demo_*.py scripts are meant for a human to run and read the output
of, but their main() functions are real code that genuinely executes
end-to-end -- calling them here for real (not mocked) both gives honest
coverage credit and catches the exact kind of regression that broke
scripts/demo.py's fixed day offset earlier (see the fix in
scripts/demo.py's STEP 5 and the parallel bug fixed in
sms_conversation._offer_reschedule_slots).
"""
import io
import sys
from contextlib import redirect_stdout

import demo as demo_module
import demo_messages
import demo_sms_conversation
import demo_new_booking
import view_audit_log


def test_scripts_demo_runs_end_to_end_without_error(fresh_db):
    buf = io.StringIO()
    with redirect_stdout(buf):
        demo_module.main()
    assert "round trip" in buf.getvalue().lower()


def test_demo_messages_runs_without_error(fresh_db):
    buf = io.StringIO()
    with redirect_stdout(buf):
        demo_messages.main()
    assert "reminder" in buf.getvalue().lower()


def test_demo_sms_conversation_runs_without_error(fresh_db):
    buf = io.StringIO()
    with redirect_stdout(buf):
        demo_sms_conversation.main()
    assert "confirmed" in buf.getvalue().lower()


def test_demo_new_booking_runs_without_error(fresh_db):
    buf = io.StringIO()
    with redirect_stdout(buf):
        demo_new_booking.main()
    assert "booked" in buf.getvalue().lower()


def test_view_audit_log_on_populated_log(fresh_db, monkeypatch):
    from audit_log import log_access
    log_access("test", "some_action", patient_id="PT-0001")
    monkeypatch.setattr(sys, "argv", ["view_audit_log.py"])  # avoid pytest's own argv leaking in
    buf = io.StringIO()
    with redirect_stdout(buf):
        view_audit_log.main()
    assert "some_action" in buf.getvalue()


def test_view_audit_log_respects_limit_argv(fresh_db, monkeypatch):
    from audit_log import log_access
    for i in range(5):
        log_access("test", f"action_{i}")
    monkeypatch.setattr(sys, "argv", ["view_audit_log.py", "2"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        view_audit_log.main()
    assert len(buf.getvalue().strip().splitlines()) == 2


def test_view_audit_log_on_empty_log(fresh_db, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["view_audit_log.py"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        view_audit_log.main()
    assert "empty" in buf.getvalue().lower()
