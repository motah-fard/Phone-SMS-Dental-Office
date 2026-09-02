"""
Read-only sanity check against the REAL production PWORKS database --
Phase 2 of docs/pwors_cutover_plan.md. Confirms the schema we learned
from TUTOR still holds against real production data, and gets rough
counts, WITHOUT ever printing a single real patient's name, phone, or
date of birth -- unlike demo_tutor.py, this is genuine PHI, not
fictional training data, so this script is deliberately more
conservative about what it shows on screen.

This does NOT write anything. SOURCE_BACKEND is never touched here.

Before running this:
  1. Create a SEPARATE DSN for PWORKS (e.g. "PWORKS_DSN") via the
     32-bit ODBC Data Source Administrator -- do NOT reuse Tutor_DSN
     pointed somewhere else. A distinct name makes it much harder to
     accidentally run a write-test script against the wrong database.
  2. Edit PWORKS_DSN_NAME below to match whatever you named it.

Run: C:\\path\\to\\32bit\\python.exe scripts\\check_pworks_readonly.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "source_system"))

from pervasive_odbc_source import read_patients_normalized, read_providers_normalized, read_appointments_normalized

PWORKS_DSN_NAME = "PWORKS_DSN"  # edit to match your real DSN name


def line():
    print("-" * 60)


def main():
    print(f"Connecting read-only to DSN={PWORKS_DSN_NAME!r} -- this DOES NOT write anything.")
    line()

    print("Reading patients (Patient File + Person file)...")
    patients = read_patients_normalized(dsn=PWORKS_DSN_NAME)
    with_phone = sum(1 for _, _, _, _, phone in patients if phone)
    with_dob = sum(1 for _, _, _, dob, _ in patients if dob)
    print(f"  {len(patients)} real patients found")
    print(f"  {with_phone} have a phone number on file ({with_phone / len(patients):.0%})" if patients else "  (none found)")
    print(f"  {with_dob} have a date of birth on file ({with_dob / len(patients):.0%})" if patients else "")
    line()

    print("Reading providers (Employee list, Can be regular Dr = True)...")
    providers = read_providers_normalized(dsn=PWORKS_DSN_NAME)
    print(f"  {len(providers)} bookable providers found")
    line()

    print("Reading appointments...")
    appointments = read_appointments_normalized(dsn=PWORKS_DSN_NAME)
    scheduled = sum(1 for a in appointments if a[5] == "scheduled")
    confirmed = sum(1 for a in appointments if a[5] == "confirmed")
    cancelled = sum(1 for a in appointments if a[5] == "cancelled")
    print(f"  {len(appointments)} real appointments found")
    print(f"  status breakdown: {scheduled} scheduled, {confirmed} confirmed, {cancelled} cancelled")
    line()

    print("No errors -- schema matches what TUTOR taught us. Nothing above reveals any")
    print("real patient's identity. Next: spot-check a few of these counts against what")
    print("the front desk actually knows (e.g. 'does ~X patients sound right?'), then")
    print("move to Phase 3 of docs/pwors_cutover_plan.md before considering any write.")


if __name__ == "__main__":
    main()
