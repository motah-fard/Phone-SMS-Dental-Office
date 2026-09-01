"""
End-to-end proof against the REAL PracticeWorks TUTOR database --
parallel to scripts/demo.py, but sourcing from Pervasive/ODBC instead
of the fake SQLite simulation. Only run this with a 32-bit Python that
has pyodbc installed and can see the Tutor_DSN ODBC data source.

Run: C:\\path\\to\\32bit\\python.exe scripts\\demo_tutor.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "mirror_system"))

from init_mirror_db import init_mirror_db, init_lookup_db
import sync as sync_module
from book import get_upcoming_appointments
from audit_log import read_recent


def line():
    print("-" * 60)


def main():
    print("STEP 1: Initialize fresh mirror + identity_lookup")
    init_mirror_db()
    init_lookup_db()
    line()

    print("STEP 2: Sync from the REAL PracticeWorks TUTOR database")
    sync_module.sync_from_pervasive()
    line()

    print("STEP 3: Show a few real (if fictional) patients now in identity_lookup")
    import sqlite3
    conn = sqlite3.connect(sync_module.LOOKUP_DB)
    rows = conn.execute(
        "SELECT patient_id, first_name, last_name, phone, dob FROM identity_map LIMIT 5"
    ).fetchall()
    conn.close()
    for patient_id, first, last, phone, dob in rows:
        print(f"  {patient_id}: {first} {last}, phone={phone}, dob={dob}")
    line()

    print("STEP 4: Look up upcoming appointments for those same patients")
    for patient_id, first, last, phone, dob in rows:
        appts = get_upcoming_appointments(patient_id, actor="demo_tutor_script")
        print(f"  {first} {last} ({patient_id}): {len(appts)} appointment(s)")
        for a in appts[:2]:
            print(f"    - {a['appt_type']} with {a['provider_name']} at {a['start_time']} [{a['status']}]")
    line()

    print("STEP 5: Recent audit log entries from this run")
    for timestamp, actor, action, patient_id, detail, success in read_recent(10):
        status = "OK" if success else "FAILED"
        print(f"  [{status}] {actor} {action} patient={patient_id} {detail}")
    line()

    print("Done -- real PracticeWorks TUTOR data flowed through the full pipeline "
          "(ODBC read -> pseudonymization -> mirror storage -> book.py query).")


if __name__ == "__main__":
    main()
