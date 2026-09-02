"""
Tests the REAL new-appointment (INSERT) write path against TUTOR --
books a brand-new appointment for a real (fictional) patient, then
re-syncs FRESH from TUTOR to confirm it actually exists on the server.

This is genuinely less certain than the reschedule write test: Visit ID
generation and which columns PracticeWorks requires on INSERT are both
unverified assumptions (see pervasive_odbc_source.write_new_appointment's
docstring). If this fails, the error text will usually name exactly
which column is missing/required -- that's expected first-try friction,
not a sign something is fundamentally broken. Report whatever error
comes back and the mapping gets adjusted from there.

Only run this against Tutor_DSN. Never set SOURCE_BACKEND=pervasive
against a DSN pointed at PWORKS.

A single clean run isn't the bar -- run this against SEVERAL different
patient_ids (see docs/pwors_cutover_plan.md Phase 1) before considering
this write path solidly proven.

Run: C:\\path\\to\\32bit\\python.exe scripts\\demo_tutor_new_booking_test.py [patient_id]
     (patient_id defaults to PT-0002 if omitted)
"""
import os
os.environ["SOURCE_BACKEND"] = "pervasive"

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "mirror_system"))

from init_mirror_db import init_mirror_db, init_lookup_db
import sync as sync_module
from book import book_new_appointment

TARGET_PATIENT_ID = sys.argv[1] if len(sys.argv) > 1 else "PT-0002"  # Stephanie Abbott, per earlier read-only test


def line():
    print("-" * 60)


def main():
    print("STEP 1: Fresh sync from the REAL TUTOR database")
    init_mirror_db()
    init_lookup_db()
    sync_module.sync_from_pervasive()
    line()

    lookup = sqlite3.connect(sync_module.LOOKUP_DB)
    row = lookup.execute(
        "SELECT source_patient_id FROM identity_map WHERE patient_id = ?", (TARGET_PATIENT_ID,)
    ).fetchone()
    lookup.close()
    if row is None:
        print(f"  {TARGET_PATIENT_ID} not found -- edit TARGET_PATIENT_ID to a valid patient_id and retry.")
        return
    source_patient_id = row[0]
    print(f"STEP 2: Booking a new appointment for {TARGET_PATIENT_ID} (real Person ID {source_patient_id})")

    # Provider 10 was Dr ID in the appointment we saw earlier -- adjust
    # if read_providers_normalized() showed a different real Employee ID.
    provider_id = 10
    start = (datetime.now() + timedelta(days=10)).replace(hour=14, minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=30)

    try:
        new_id = book_new_appointment(
            TARGET_PATIENT_ID, source_patient_id, provider_id, start, end,
            appt_type="Test Booking", actor="demo_tutor_new_booking_test",
        )
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        print("  This is expected-possible first-try friction -- the error above usually names")
        print("  exactly which column PracticeWorks needs that write_new_appointment() didn't set.")
        return
    print(f"  book_new_appointment() succeeded, real Visit ID = {new_id}")
    line()

    print("STEP 3: Re-sync FRESH from TUTOR and confirm the new appointment really exists")
    init_mirror_db()
    init_lookup_db()
    sync_module.sync_from_pervasive()
    conn = sqlite3.connect(sync_module.MIRROR_DB)
    after = conn.execute(
        "SELECT patient_id, provider_id, start_time, end_time FROM appointments WHERE id = ?", (new_id,)
    ).fetchone()
    conn.close()
    if after is None:
        print(f"  MISMATCH -- appointment {new_id} doesn't show up after a fresh sync. Investigate.")
    else:
        print(f"  Appointment #{new_id} now reads from TUTOR as: {after}")
        print("  SUCCESS -- the real new appointment persisted on the PracticeWorks server.")
    line()


if __name__ == "__main__":
    main()
