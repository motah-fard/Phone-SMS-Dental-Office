"""
End-to-end proof-of-concept:
  1. Build the fake source (PracticeWorks) DB.
  2. Sync it into the pseudonymized mirror + identity_lookup.
  3. Simulate an inbound call/text from a known phone number asking to
     reschedule.
  4. Resolve identity, check availability, pick a new slot, write back.
  5. Re-sync and prove the change landed in the source system.

Run: python3 scripts/demo.py
"""
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "source_system"))
sys.path.insert(0, str(Path(__file__).parent.parent / "mirror_system"))

from init_source_db import init_db as init_source_db
from init_mirror_db import init_mirror_db, init_lookup_db
import sync as sync_module
from availability import get_open_slots
from book import resolve_patient_by_phone, get_upcoming_appointments, reschedule_appointment

SOURCE_DB = Path(__file__).parent.parent / "source_system" / "practiceworks_sim.db"


def line():
    print("-" * 60)


def main():
    print("STEP 1: Build fake source (PracticeWorks) database")
    init_source_db()
    line()

    print("STEP 2: Initialize mirror + identity_lookup, then sync")
    init_mirror_db()
    init_lookup_db()
    sync_module.sync()
    line()

    caller_phone = "+15551230001"
    print(f"STEP 3: Inbound call/text from {caller_phone} — 'I need to reschedule'")
    patient = resolve_patient_by_phone(caller_phone, actor="demo_script")
    print(f"  Resolved to pseudonymous patient_id={patient['patient_id']} "
          f"(first name '{patient['first_name']}' known ONLY to identity_lookup.db, "
          f"never touched by anything past this point)")
    line()

    print("STEP 4: Look up this patient's upcoming appointment(s) in the mirror DB (no PHI involved)")
    appts = get_upcoming_appointments(patient["patient_id"], actor="demo_script")
    for a in appts:
        print(f"  Appointment #{a['appointment_id']}: {a['appt_type']} with {a['provider_name']} "
              f"at {a['start_time']} [{a['status']}]")
    target = appts[0]
    line()

    print(f"STEP 5: Find open slots with {target['provider_name']} two days out")
    day = datetime.now() + timedelta(days=2)
    slots = get_open_slots(target["provider_id"], day)
    for s, e in slots[:5]:
        print(f"  Available: {s.strftime('%Y-%m-%d %H:%M')} - {e.strftime('%H:%M')}")
    new_start, new_end = slots[2]
    print(f"  -> Offering and booking: {new_start.strftime('%Y-%m-%d %H:%M')}")
    line()

    print("STEP 6: Reschedule (writes to mirror, then writes back to source)")
    reschedule_appointment(
        target["appointment_id"], new_start, new_end, patient["source_patient_id"],
        actor="demo_script", patient_id=patient["patient_id"],
    )
    line()

    print("STEP 7: Verify the write-back actually landed in the source (PracticeWorks) DB")
    conn = sqlite3.connect(SOURCE_DB)
    row = conn.execute(
        "SELECT start_time, end_time, status FROM appointments WHERE id = ?",
        (target["appointment_id"],),
    ).fetchone()
    conn.close()
    print(f"  Source DB now shows appointment #{target['appointment_id']}: "
          f"start={row[0]}, end={row[1]}, status={row[2]}")
    line()

    print("STEP 8: Re-sync and confirm mirror reflects the same change")
    sync_module.sync()
    appts_after = get_upcoming_appointments(patient["patient_id"], actor="demo_script")
    for a in appts_after:
        if a["appointment_id"] == target["appointment_id"]:
            print(f"  Mirror DB now shows: {a['start_time']} [{a['status']}]")
    line()
    print("Done — full round trip (identity resolution -> availability -> reschedule -> write-back -> re-sync) verified.")


if __name__ == "__main__":
    main()
