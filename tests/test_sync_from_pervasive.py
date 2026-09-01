"""
sync.py's sync_from_pervasive() -- testable without a real ODBC
connection because it imports pervasive_odbc_source lazily, inside the
function body, rather than at module load time. Injecting a fake module
into sys.modules under that name intercepts the import before Python
ever touches the real (pyodbc-dependent) file, the same way the fake
LLM clients stand in for a real API in test_llm_fallback.py.

This tests OUR sync logic (identity reuse, orphan-appointment skipping,
error wrapping) against controlled fake data shaped like the real
normalized readers -- not real PracticeWorks connectivity, which can
only be verified on a machine with the actual ODBC driver.
"""
import sqlite3
import sys
import types

import sync as sync_module


def install_fake_pervasive_source(monkeypatch, patients, providers, appointments):
    fake_module = types.ModuleType("pervasive_odbc_source")
    fake_module.read_patients_normalized = lambda: patients
    fake_module.read_providers_normalized = lambda: providers
    fake_module.read_appointments_normalized = lambda: appointments
    monkeypatch.setitem(sys.modules, "pervasive_odbc_source", fake_module)


def test_sync_from_pervasive_populates_mirror_and_lookup(fresh_db, monkeypatch):
    install_fake_pervasive_source(
        monkeypatch,
        patients=[(101, "Real", "Patient", "1990-01-01", "+15559990001")],
        providers=[(5, "Dr. Real", "08:00", "17:00")],
        appointments=[(9001, 101, 5, "2026-09-01T09:00:00", "2026-09-01T09:30:00", "scheduled", "checkup")],
    )

    sync_module.sync_from_pervasive()

    lookup = sqlite3.connect(sync_module.LOOKUP_DB)
    row = lookup.execute("SELECT first_name, phone, dob FROM identity_map WHERE source_patient_id = 101").fetchone()
    lookup.close()
    assert row == ("Real", "+15559990001", "1990-01-01")

    mirror = sqlite3.connect(sync_module.MIRROR_DB)
    provider_row = mirror.execute("SELECT name FROM providers WHERE id = 5").fetchone()
    appt_row = mirror.execute("SELECT start_time, appt_type FROM appointments WHERE id = 9001").fetchone()
    mirror.close()
    assert provider_row == ("Dr. Real",)
    assert appt_row == ("2026-09-01T09:00:00", "checkup")


def test_sync_from_pervasive_skips_appointment_with_unknown_patient(fresh_db, monkeypatch):
    install_fake_pervasive_source(
        monkeypatch,
        patients=[(101, "Real", "Patient", "1990-01-01", "+15559990001")],
        providers=[(5, "Dr. Real", "08:00", "17:00")],
        appointments=[(9002, 999, 5, "2026-09-01T09:00:00", "2026-09-01T09:30:00", "scheduled", "checkup")],
    )

    sync_module.sync_from_pervasive()  # must not raise

    mirror = sqlite3.connect(sync_module.MIRROR_DB)
    count = mirror.execute("SELECT COUNT(*) FROM appointments WHERE id = 9002").fetchone()[0]
    mirror.close()
    assert count == 0


def test_sync_from_pervasive_reuses_pseudonym_across_reruns(fresh_db, monkeypatch):
    install_fake_pervasive_source(
        monkeypatch,
        patients=[(101, "Real", "Patient", "1990-01-01", "+15559990001")],
        providers=[(5, "Dr. Real", "08:00", "17:00")],
        appointments=[],
    )
    sync_module.sync_from_pervasive()
    lookup = sqlite3.connect(sync_module.LOOKUP_DB)
    first_id = lookup.execute("SELECT patient_id FROM identity_map WHERE source_patient_id = 101").fetchone()[0]
    lookup.close()

    sync_module.sync_from_pervasive()
    lookup = sqlite3.connect(sync_module.LOOKUP_DB)
    second_id = lookup.execute("SELECT patient_id FROM identity_map WHERE source_patient_id = 101").fetchone()[0]
    lookup.close()

    assert first_id == second_id


def test_sync_from_pervasive_raises_sync_error_on_reader_failure(fresh_db, monkeypatch):
    fake_module = types.ModuleType("pervasive_odbc_source")

    def boom():
        raise RuntimeError("simulated ODBC failure")

    fake_module.read_patients_normalized = lambda: []
    fake_module.read_providers_normalized = boom
    fake_module.read_appointments_normalized = lambda: []
    monkeypatch.setitem(sys.modules, "pervasive_odbc_source", fake_module)

    import pytest
    with pytest.raises(sync_module.SyncError):
        sync_module.sync_from_pervasive()
