"""
source_system/init_source_db.py and mirror_system/init_mirror_db.py --
these mostly just create schema and seed data, but worth verifying the
schema/seed counts directly rather than only through fresh_db's
indirect use in every other test file.
"""
import sqlite3

import init_source_db as isd
import init_mirror_db as imd


def test_init_source_db_creates_expected_tables():
    isd.init_db()
    conn = sqlite3.connect(isd.DB_PATH)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"patients", "providers", "appointments"} <= tables


def test_init_source_db_seeds_expected_counts():
    isd.init_db()
    conn = sqlite3.connect(isd.DB_PATH)
    patients = conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
    providers = conn.execute("SELECT COUNT(*) FROM providers").fetchone()[0]
    appointments = conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
    conn.close()
    assert patients == 4
    assert providers == 2
    assert appointments == 4


def test_init_source_db_is_idempotent_rerun_does_not_duplicate():
    isd.init_db()
    isd.init_db()
    conn = sqlite3.connect(isd.DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
    conn.close()
    assert count == 4


def test_init_mirror_db_creates_expected_tables_empty():
    imd.init_mirror_db()
    conn = sqlite3.connect(imd.MIRROR_DB_PATH)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    appt_count = conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
    conn.close()
    assert {"providers", "appointments"} <= tables
    assert appt_count == 0  # freshly created, not synced yet


def test_init_lookup_db_creates_empty_identity_map():
    imd.init_lookup_db()
    conn = sqlite3.connect(imd.LOOKUP_DB_PATH)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(identity_map)")}
    count = conn.execute("SELECT COUNT(*) FROM identity_map").fetchone()[0]
    conn.close()
    assert columns == {"patient_id", "source_patient_id", "first_name", "last_name", "phone", "dob"}
    assert count == 0
