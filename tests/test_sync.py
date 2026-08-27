"""scripts/sync.py -- source -> mirror + identity_lookup sync."""
import sqlite3
from pathlib import Path

import pytest

import sync as sync_module


def test_sync_creates_pseudonymous_identities_for_all_source_patients(fresh_db):
    conn = sqlite3.connect(sync_module.LOOKUP_DB)
    count = conn.execute("SELECT COUNT(*) FROM identity_map").fetchone()[0]
    conn.close()
    assert count == 4  # 4 seeded patients in init_source_db.py


def test_sync_carries_no_phi_into_mirror_appointments(fresh_db):
    """The mirror appointments table must never end up with a name,
    phone, or dob column populated -- verify by inspecting the actual
    schema, not just trusting the code."""
    conn = sqlite3.connect(sync_module.MIRROR_DB)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(appointments)")}
    conn.close()
    assert columns == {"id", "patient_id", "provider_id", "start_time", "end_time", "status", "appt_type"}
    assert "first_name" not in columns and "phone" not in columns


def test_sync_is_idempotent_reruns_do_not_duplicate_identities(fresh_db):
    sync_module.sync()
    sync_module.sync()
    conn = sqlite3.connect(sync_module.LOOKUP_DB)
    count = conn.execute("SELECT COUNT(*) FROM identity_map").fetchone()[0]
    conn.close()
    assert count == 4


def test_sync_reuses_same_pseudonym_across_reruns(fresh_db):
    conn = sqlite3.connect(sync_module.LOOKUP_DB)
    before = conn.execute("SELECT patient_id FROM identity_map WHERE source_patient_id = 1").fetchone()[0]
    conn.close()

    sync_module.sync()

    conn = sqlite3.connect(sync_module.LOOKUP_DB)
    after = conn.execute("SELECT patient_id FROM identity_map WHERE source_patient_id = 1").fetchone()[0]
    conn.close()
    assert before == after


def test_next_patient_id_starts_at_0001_when_empty(fresh_db):
    conn = sqlite3.connect(sync_module.LOOKUP_DB)
    conn.execute("DELETE FROM identity_map")
    conn.commit()
    cur = conn.cursor()
    assert sync_module.next_patient_id(cur) == "PT-0001"
    conn.close()


def test_next_patient_id_increments(fresh_db):
    conn = sqlite3.connect(sync_module.LOOKUP_DB)
    cur = conn.cursor()
    next_id = sync_module.next_patient_id(cur)
    n = int(next_id.split("-")[1])
    assert n == 5  # 4 already exist from fresh_db's sync
    conn.close()


def test_sync_skips_appointment_with_no_matching_patient_instead_of_crashing(fresh_db):
    """Defensive branch: an appointment referencing a patient id that
    somehow isn't in source_to_pseudo (shouldn't happen since every
    patient gets synced first, but source data could be inconsistent).
    Must skip and log, not crash the whole sync."""
    conn = sqlite3.connect(sync_module.SOURCE_DB)
    conn.execute(
        "INSERT INTO appointments VALUES (999, 9999, 1, '2026-09-01T09:00:00', '2026-09-01T09:30:00', 'scheduled', 'orphan')"
    )
    conn.commit()
    conn.close()

    sync_module.sync()  # must not raise

    mirror = sqlite3.connect(sync_module.MIRROR_DB)
    orphan_in_mirror = mirror.execute("SELECT COUNT(*) FROM appointments WHERE id = 999").fetchone()[0]
    mirror.close()
    assert orphan_in_mirror == 0


def test_sync_raises_sync_error_on_db_failure(fresh_db, monkeypatch):
    monkeypatch.setattr(sync_module, "MIRROR_DB", Path("/nonexistent_dir_xyz_12345/mirror.db"))
    with pytest.raises(sync_module.SyncError):
        sync_module.sync()
