"""
scripts/book.py -- the channel-agnostic layer everything else calls
through. Covers the happy paths, the security-relevant behaviors
(reschedule can't touch another patient's appointment even with a
guessed id), and the error-handling paths (SchedulingError on a DB
failure, not a raw crash).
"""
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import book


def test_resolve_patient_by_phone_found(fresh_db):
    patient = book.resolve_patient_by_phone("+15551230001", actor="test")
    assert patient is not None
    assert patient["patient_id"] == "PT-0001"
    assert patient["first_name"] == "Maria"


def test_resolve_patient_by_phone_not_found(fresh_db):
    assert book.resolve_patient_by_phone("+19995550000", actor="test") is None


def test_verify_patient_correct_dob_succeeds(fresh_db):
    patient = book.verify_patient("+15551230001", "1988-04-12", actor="test")
    assert patient is not None
    assert patient["patient_id"] == "PT-0001"


def test_verify_patient_wrong_dob_fails(fresh_db):
    assert book.verify_patient("+15551230001", "1999-01-01", actor="test") is None


def test_verify_patient_correct_dob_wrong_phone_fails(fresh_db):
    """Both factors must match the SAME record -- a correct dob paired
    with someone else's phone must not succeed."""
    assert book.verify_patient("+15551230002", "1988-04-12", actor="test") is None


@pytest.mark.parametrize("raw,expected", [
    ("04/12/1988", "1988-04-12"),
    ("04-12-1988", "1988-04-12"),
    ("4/12/88", "1988-04-12"),
    ("1988-04-12", "1988-04-12"),
])
def test_parse_dob_accepts_common_formats(raw, expected):
    assert book.parse_dob(raw) == expected


@pytest.mark.parametrize("garbage", ["not a date", "", "13/45/2020", "March 3rd"])
def test_parse_dob_rejects_unparseable_input(garbage):
    assert book.parse_dob(garbage) is None


def test_get_upcoming_appointments_returns_expected_shape(fresh_db):
    patient = book.resolve_patient_by_phone("+15551230001", actor="test")
    appts = book.get_upcoming_appointments(patient["patient_id"], actor="test")
    assert len(appts) == 1
    appt = appts[0]
    assert appt["appt_type"] == "cleaning"
    assert appt["provider_name"] == "Dr. Lee"
    assert appt["status"] == "scheduled"


def test_get_upcoming_appointments_excludes_cancelled(fresh_db):
    import sqlite3
    conn = sqlite3.connect(book.MIRROR_DB)
    conn.execute("UPDATE appointments SET status = 'cancelled' WHERE patient_id = 'PT-0001'")
    conn.commit()
    conn.close()

    assert book.get_upcoming_appointments("PT-0001", actor="test") == []


def test_get_upcoming_appointments_unknown_patient_returns_empty(fresh_db):
    assert book.get_upcoming_appointments("PT-9999", actor="test") == []


def test_get_upcoming_appointments_excludes_past_appointments(fresh_db):
    """Regression test: found via real PracticeWorks TUTOR data, which
    (unlike our own fake seed data) includes years of appointment
    history -- a 2015-dated visit must never show up as 'upcoming'."""
    import sqlite3
    conn = sqlite3.connect(book.MIRROR_DB)
    conn.execute(
        "UPDATE appointments SET start_time = '2015-01-05T10:30:00', end_time = '2015-01-05T11:00:00' "
        "WHERE patient_id = 'PT-0001'"
    )
    conn.commit()
    conn.close()

    assert book.get_upcoming_appointments("PT-0001", actor="test") == []


def test_reschedule_appointment_updates_mirror_and_source(fresh_db):
    patient = book.resolve_patient_by_phone("+15551230001", actor="test")
    appt = book.get_upcoming_appointments(patient["patient_id"], actor="test")[0]
    new_start = datetime.now() + timedelta(days=3)
    new_end = new_start + timedelta(minutes=30)

    book.reschedule_appointment(
        appt["appointment_id"], new_start, new_end, patient["source_patient_id"],
        actor="test", patient_id=patient["patient_id"],
    )

    updated = book.get_upcoming_appointments(patient["patient_id"], actor="test")[0]
    assert updated["start_time"] == new_start.isoformat()
    assert updated["status"] == "confirmed"

    import sqlite3
    src = sqlite3.connect(book.SOURCE_DB)
    row = src.execute(
        "SELECT start_time, status FROM appointments WHERE id = ?", (appt["appointment_id"],)
    ).fetchone()
    src.close()
    assert row == (new_start.isoformat(), "confirmed")


def test_reschedule_appointment_cannot_move_another_patients_appointment(fresh_db):
    """Security property: the source write is scoped by patient_id too --
    passing the WRONG source_patient_id for a real appointment_id must
    not silently move someone else's appointment."""
    patient1 = book.resolve_patient_by_phone("+15551230001", actor="test")
    appt = book.get_upcoming_appointments(patient1["patient_id"], actor="test")[0]
    wrong_patient = book.resolve_patient_by_phone("+15551230002", actor="test")
    new_start = datetime.now() + timedelta(days=3)
    new_end = new_start + timedelta(minutes=30)

    # Mirror has no patient_id guard (by appointment id alone), but the
    # source write requires a matching patient_id and will silently no-op
    # if it doesn't match -- confirm the SOURCE row is untouched.
    import sqlite3
    src = sqlite3.connect(book.SOURCE_DB)
    original = src.execute(
        "SELECT start_time FROM appointments WHERE id = ?", (appt["appointment_id"],)
    ).fetchone()
    src.close()

    book.reschedule_appointment(
        appt["appointment_id"], new_start, new_end, wrong_patient["source_patient_id"],
        actor="test", patient_id=wrong_patient["patient_id"],
    )

    src = sqlite3.connect(book.SOURCE_DB)
    after = src.execute(
        "SELECT start_time FROM appointments WHERE id = ?", (appt["appointment_id"],)
    ).fetchone()
    src.close()
    assert after == original  # unchanged -- the WHERE clause's patient_id guard held


def test_book_new_appointment_creates_row_in_both_databases(fresh_db):
    patient = book.resolve_patient_by_phone("+15551230001", actor="test")
    start = datetime.now() + timedelta(days=5)
    end = start + timedelta(minutes=30)

    new_id = book.book_new_appointment(
        patient["patient_id"], patient["source_patient_id"], provider_id=1,
        start=start, end=end, actor="test",
    )

    import sqlite3
    mirror = sqlite3.connect(book.MIRROR_DB)
    mirror_row = mirror.execute("SELECT patient_id, status FROM appointments WHERE id = ?", (new_id,)).fetchone()
    mirror.close()
    assert mirror_row == (patient["patient_id"], "confirmed")

    src = sqlite3.connect(book.SOURCE_DB)
    src_row = src.execute("SELECT patient_id, status FROM appointments WHERE id = ?", (new_id,)).fetchone()
    src.close()
    assert src_row == (patient["source_patient_id"], "confirmed")


def test_book_new_appointment_id_does_not_collide_with_existing(fresh_db):
    patient = book.resolve_patient_by_phone("+15551230001", actor="test")
    existing_ids = {a["appointment_id"] for a in book.get_upcoming_appointments(patient["patient_id"], actor="test")}
    start = datetime.now() + timedelta(days=5)
    new_id = book.book_new_appointment(
        patient["patient_id"], patient["source_patient_id"], 1, start, start + timedelta(minutes=30), actor="test",
    )
    assert new_id not in existing_ids


def test_resolve_patient_by_phone_raises_scheduling_error_on_db_failure(fresh_db, monkeypatch):
    """Points LOOKUP_DB at a location sqlite can't open, forcing a real
    sqlite3.Error -- confirms it's wrapped into SchedulingError rather
    than leaking a raw sqlite3 exception to callers."""
    monkeypatch.setattr(book, "LOOKUP_DB", Path("/nonexistent_dir_xyz_12345/identity_lookup.db"))
    with pytest.raises(book.SchedulingError):
        book.resolve_patient_by_phone("+15551230001", actor="test")


def test_reschedule_appointment_raises_scheduling_error_on_mirror_failure(fresh_db, monkeypatch):
    monkeypatch.setattr(book, "MIRROR_DB", Path("/nonexistent_dir_xyz_12345/mirror.db"))
    with pytest.raises(book.SchedulingError):
        book.reschedule_appointment(1, datetime.now(), datetime.now(), 1, actor="test")


def test_reschedule_appointment_raises_scheduling_error_when_source_write_fails(fresh_db, monkeypatch):
    """Mirror write must succeed first (real MIRROR_DB), only the SOURCE
    write fails -- exercises the second except block, distinct from the
    mirror-failure test above."""
    monkeypatch.setattr(book, "SOURCE_DB", Path("/nonexistent_dir_xyz_12345/source.db"))
    with pytest.raises(book.SchedulingError):
        book.reschedule_appointment(1, datetime.now(), datetime.now(), 1, actor="test")


def test_reschedule_appointment_uses_pervasive_write_when_backend_selected(fresh_db, monkeypatch):
    """SOURCE_BACKEND=pervasive must call pervasive_odbc_source.write_reschedule
    instead of touching the fake SOURCE_DB -- proven with a fake module
    injected into sys.modules, same technique as test_sync_from_pervasive.py,
    since the real file needs pyodbc + a live ODBC connection."""
    calls = []
    fake_module = types.ModuleType("pervasive_odbc_source")
    fake_module.write_reschedule = lambda visit_id, new_start, new_end: calls.append((visit_id, new_start, new_end))
    monkeypatch.setitem(sys.modules, "pervasive_odbc_source", fake_module)
    monkeypatch.setattr(book, "SOURCE_BACKEND", "pervasive")

    patient = book.resolve_patient_by_phone("+15551230001", actor="test")
    appt = book.get_upcoming_appointments(patient["patient_id"], actor="test")[0]
    new_start = datetime.now() + timedelta(days=3)
    new_end = new_start + timedelta(minutes=30)

    book.reschedule_appointment(
        appt["appointment_id"], new_start, new_end, patient["source_patient_id"], actor="test",
    )

    assert calls == [(appt["appointment_id"], new_start, new_end)]


def test_reschedule_appointment_pervasive_failure_raises_scheduling_error(fresh_db, monkeypatch):
    fake_module = types.ModuleType("pervasive_odbc_source")

    def boom(visit_id, new_start, new_end):
        raise RuntimeError("simulated ODBC write failure")

    fake_module.write_reschedule = boom
    monkeypatch.setitem(sys.modules, "pervasive_odbc_source", fake_module)
    monkeypatch.setattr(book, "SOURCE_BACKEND", "pervasive")

    with pytest.raises(book.SchedulingError):
        book.reschedule_appointment(1, datetime.now(), datetime.now(), 1, actor="test")


def test_verify_patient_raises_scheduling_error_on_db_failure(fresh_db, monkeypatch):
    monkeypatch.setattr(book, "LOOKUP_DB", Path("/nonexistent_dir_xyz_12345/identity_lookup.db"))
    with pytest.raises(book.SchedulingError):
        book.verify_patient("+15551230001", "1988-04-12", actor="test")


def test_get_upcoming_appointments_raises_scheduling_error_on_db_failure(fresh_db, monkeypatch):
    monkeypatch.setattr(book, "MIRROR_DB", Path("/nonexistent_dir_xyz_12345/mirror.db"))
    with pytest.raises(book.SchedulingError):
        book.get_upcoming_appointments("PT-0001", actor="test")


def _fail_on_nth_connect_to(target_path, fail_on_call_number):
    """Returns a fake sqlite3.connect that behaves normally for every
    real path EXCEPT target_path, where it succeeds normally until the
    fail_on_call_number'th connection to that specific path, then raises
    -- used to isolate "the read succeeded, but the later write to the
    same database failed" without needing two different broken paths."""
    import sqlite3
    real_connect = sqlite3.connect
    call_count = {"n": 0}

    def fake_connect(path, *args, **kwargs):
        if str(path) == str(target_path):
            call_count["n"] += 1
            if call_count["n"] >= fail_on_call_number:
                raise sqlite3.OperationalError("simulated failure on later connection to this db")
        return real_connect(path, *args, **kwargs)

    return fake_connect


def test_book_new_appointment_raises_scheduling_error_on_id_generation_failure(fresh_db, monkeypatch):
    monkeypatch.setattr(book, "MIRROR_DB", Path("/nonexistent_dir_xyz_12345/mirror.db"))
    with pytest.raises(book.SchedulingError):
        book.book_new_appointment("PT-0001", 1, 1, datetime.now(), datetime.now(), actor="test")


def test_book_new_appointment_raises_scheduling_error_when_mirror_insert_fails(fresh_db, monkeypatch):
    """Id generation reads MIRROR_DB successfully (1st connection); the
    later INSERT into MIRROR_DB (2nd connection) is what fails."""
    monkeypatch.setattr(book.sqlite3, "connect", _fail_on_nth_connect_to(book.MIRROR_DB, fail_on_call_number=2))
    with pytest.raises(book.SchedulingError):
        book.book_new_appointment("PT-0001", 1, 1, datetime.now(), datetime.now() + timedelta(minutes=30), actor="test")


def test_book_new_appointment_raises_scheduling_error_when_source_insert_fails(fresh_db, monkeypatch):
    """Id generation reads SOURCE_DB successfully (1st connection); the
    later INSERT into SOURCE_DB (2nd connection) is what fails -- the
    mirror insert must have already succeeded by this point."""
    monkeypatch.setattr(book.sqlite3, "connect", _fail_on_nth_connect_to(book.SOURCE_DB, fail_on_call_number=2))
    with pytest.raises(book.SchedulingError):
        book.book_new_appointment("PT-0001", 1, 1, datetime.now(), datetime.now() + timedelta(minutes=30), actor="test")
