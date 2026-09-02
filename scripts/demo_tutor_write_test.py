"""
Tests the REAL write-back path against TUTOR: reschedules one known
appointment to a new near-future time, then re-syncs FRESH from TUTOR
to confirm the change actually persisted on the real server -- not
just in our local mirror.

A single clean run isn't the bar -- run this against SEVERAL different
patient_ids (see docs/pwors_cutover_plan.md Phase 1) before considering
the write path solidly proven, since one pass could succeed on a
patient/appointment combination that happens to avoid some constraint
a different one would hit.

Only run this against Tutor_DSN. Never set SOURCE_BACKEND=pervasive
against a DSN pointed at PWORKS.

Run: C:\\path\\to\\32bit\\python.exe scripts\\demo_tutor_write_test.py [patient_id]
     (patient_id defaults to PT-0002 if omitted -- pass a different one,
     e.g. PT-0001 or PT-0004, to test against another real patient)
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
from book import reschedule_appointment

TARGET_PATIENT_ID = sys.argv[1] if len(sys.argv) > 1 else "PT-0002"


def line():
    print("-" * 60)


def main():
    print("STEP 1: Fresh sync from the REAL TUTOR database")
    init_mirror_db()
    init_lookup_db()
    sync_module.sync_from_pervasive()
    line()

    print(f"STEP 2: Look up {TARGET_PATIENT_ID}'s appointment directly in the mirror")
    conn = sqlite3.connect(sync_module.MIRROR_DB)
    row = conn.execute(
        "SELECT id, start_time, end_time FROM appointments WHERE patient_id = ? ORDER BY start_time LIMIT 1",
        (TARGET_PATIENT_ID,),
    ).fetchone()
    conn.close()
    if row is None:
        print(f"  No appointment found for {TARGET_PATIENT_ID} -- edit TARGET_PATIENT_ID to a patient_id "
              f"that demo_tutor.py showed has one, and retry.")
        return
    appointment_id, old_start, old_end = row
    print(f"  Found appointment #{appointment_id}: {old_start} - {old_end}")
    line()

    lookup = sqlite3.connect(sync_module.LOOKUP_DB)
    source_patient_id = lookup.execute(
        "SELECT source_patient_id FROM identity_map WHERE patient_id = ?", (TARGET_PATIENT_ID,)
    ).fetchone()[0]
    lookup.close()

    new_start = (datetime.now() + timedelta(days=7)).replace(hour=10, minute=0, second=0, microsecond=0)
    new_end = new_start + timedelta(minutes=30)
    print(f"STEP 3: Reschedule appointment #{appointment_id} to {new_start} "
          f"(SOURCE_BACKEND=pervasive -- this writes to the real TUTOR database)")
    reschedule_appointment(
        appointment_id, new_start, new_end, source_patient_id,
        actor="demo_tutor_write_test", patient_id=TARGET_PATIENT_ID,
    )
    print("  reschedule_appointment() completed without raising.")
    line()

    print("STEP 4: Re-sync FRESH from TUTOR (a brand new read) and confirm the change really persisted")
    init_mirror_db()
    init_lookup_db()
    sync_module.sync_from_pervasive()
    conn = sqlite3.connect(sync_module.MIRROR_DB)
    after = conn.execute(
        "SELECT start_time, end_time FROM appointments WHERE id = ?", (appointment_id,)
    ).fetchone()
    conn.close()
    print(f"  Appointment #{appointment_id} now reads from TUTOR as: {after[0]} - {after[1]}")
    if after[0] == new_start.isoformat():
        print("  SUCCESS -- the real write persisted on the PracticeWorks server, confirmed by a fresh read.")
    else:
        print(f"  MISMATCH -- expected {new_start.isoformat()}, got {after[0]}. Investigate before trusting this path.")
    line()


if __name__ == "__main__":
    main()
