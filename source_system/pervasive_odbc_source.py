"""
Real PracticeWorks connector, replacing init_source_db.py's fake SQLite
database now that the real schema is confirmed (see
docs/practiceworks_schema_notes.md for the full column dump this was
built from).

Connects to the Pervasive PSQL / Btrieve engine over ODBC. DSN_NAME
points at TUTOR (training data) -- never point this at PWORKS until
everything here is verified correct against TUTOR first.

DSN_NAME below ("Tutor_DSN") was created via the 32-bit ODBC Data
Source Administrator, using the "Pervasive ODBC Client Interface"
driver, Server Name/IP = W-SRV-VM-102, Database Name = TUTOR.

IMPORTANT: this is a 32-bit DSN. A 64-bit Python interpreter cannot see
or use it -- see the project's earlier setup notes if this needs
re-confirming. Requires: pip install pyodbc (into the matching-bitness
interpreter).

Schema findings baked into the queries below:
- "Patient File" has NO phone or date-of-birth column. Those live on
  the generic "Person file" table instead (shared by patients,
  referral sources, employees, etc.), joined by Person ID. Patients
  are identified by inner-joining Patient File -> Person file.
- Negative Person IDs (e.g. -4 "~Unknown~"/"~Patient~", -5
  "~ReferralSrc~") are PracticeWorks' internal placeholder records, not
  real people -- filtered out everywhere below.
- "Appointments" stores "Date" and "Start time"/"End time" as SEPARATE
  date/time values, not one combined datetime -- combined here via
  datetime.combine(). Appointments also have variable durations in
  practice (confirmed from real sample rows: 49 min, 39 min), not the
  fixed 30-minute slots this project's own NEW-booking logic offers --
  that's fine, the overlap-detection in availability.py works with
  busy blocks of any length; only newly-offered slots are fixed-length.
- "Open Close Times" turned out to be a date-specific exception/holiday
  table (3 columns: Date, OpenTime, CloseTime), not a recurring weekly
  schedule, and it's empty in TUTOR. No real per-provider hours source
  has been found yet, so read_providers_normalized() falls back to the
  practice's stated hours (8am-5pm) for every provider. Revisit if a
  real hours source turns up later.
"""
from datetime import datetime

import pyodbc

DSN_NAME = "Tutor_DSN"

DEFAULT_WORK_START = "08:00"
DEFAULT_WORK_END = "17:00"


def get_connection():
    return pyodbc.connect(f"DSN={DSN_NAME};")


# --- Raw readers (full SELECT *, for inspection -- see __main__ below) ---

def read_patients():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM "Patient File"')
    columns = [c[0] for c in cur.description]
    rows = cur.fetchall()
    conn.close()
    return columns, rows


def read_appointments():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM "Appointments"')
    columns = [c[0] for c in cur.description]
    rows = cur.fetchall()
    conn.close()
    return columns, rows


def read_providers():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM "Employee list"')
    columns = [c[0] for c in cur.description]
    rows = cur.fetchall()
    conn.close()
    return columns, rows


def read_person_file():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM "Person file"')
    columns = [c[0] for c in cur.description]
    rows = cur.fetchall()
    conn.close()
    return columns, rows


def read_work_hours():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM "Open Close Times"')
    columns = [c[0] for c in cur.description]
    rows = cur.fetchall()
    conn.close()
    return columns, rows


# --- Normalized readers: shaped exactly like source_system.init_source_db's
# fake tables, so scripts/sync.py's sync_from_pervasive() can populate
# mirror.db/identity_lookup.db the same way regardless of source. ---

def read_patients_normalized():
    """Returns (person_id, first_name, last_name, dob_iso_or_None, phone)
    tuples for real patients only (Person ID > 0, actually present in
    Patient File)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT pf."Person ID", pf."First name", pf."Last name", pf."Birthdate", pf."Home phone"
        FROM "Patient File" p
        JOIN "Person file" pf ON pf."Person ID" = p."Person ID"
        WHERE p."Person ID" > 0
        """
    )
    rows = cur.fetchall()
    conn.close()
    return [
        (person_id, first, last, birthdate.isoformat() if birthdate else None, phone)
        for person_id, first, last, birthdate, phone in rows
    ]


def read_providers_normalized():
    """Returns (employee_id, display_name, work_start, work_end) tuples
    for staff who can actually be booked as a treating provider (`Can
    be regular Dr` = True) -- excludes front desk/hygienist-only staff
    from what patients are offered as a provider choice."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT "Employee ID", "First name", "Last name", "Can be regular Dr" FROM "Employee list"')
    rows = cur.fetchall()
    conn.close()
    return [
        (emp_id, f"Dr. {last}", DEFAULT_WORK_START, DEFAULT_WORK_END)
        for emp_id, first, last, can_be_dr in rows
        if can_be_dr
    ]


def read_appointments_normalized():
    """Returns (visit_id, patient_id, provider_id, start_iso, end_iso,
    status, appt_type) tuples for real appointments (Patient ID > 0).
    status is inferred: cancelled if Cancel status is set, confirmed if
    a Confirmed date is on file, otherwise scheduled -- there's no
    human-readable status legend in the schema, this is the best
    available signal."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT "Visit ID", "Patient ID", "Dr ID", "Date", "Start time", "End time",
               "Cancel status", "Confirmed date", "Description"
        FROM "Appointments"
        WHERE "Patient ID" > 0
        """
    )
    rows = cur.fetchall()
    conn.close()

    result = []
    for visit_id, patient_id, dr_id, date, start_t, end_t, cancel_status, confirmed_date, description in rows:
        start_dt = datetime.combine(date, start_t)
        end_dt = datetime.combine(date, end_t)
        if cancel_status:
            status = "cancelled"
        elif confirmed_date:
            status = "confirmed"
        else:
            status = "scheduled"
        result.append((visit_id, patient_id, dr_id, start_dt.isoformat(), end_dt.isoformat(), status, description))
    return result


# --- Writes: start with reschedule (UPDATE an existing row) only.
# Deliberately NOT building "create a new appointment" (INSERT) yet --
# that needs real-world confirmation of how Visit ID and other
# required fields (Resource ID, Tx class ID, etc.) get assigned, which
# hasn't been investigated. Updating a known existing row is much
# lower-risk than guessing at insert requirements. ---

def write_reschedule(visit_id, new_start, new_end):
    """Moves an EXISTING appointment (identified by its real Visit ID)
    to a new date/time. Splits the datetime back into separate Date/
    Start time/End time columns -- the reverse of how they're combined
    in read_appointments_normalized(). Leaves Cancel status/Confirmed
    date untouched."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        'UPDATE "Appointments" SET "Date" = ?, "Start time" = ?, "End time" = ? WHERE "Visit ID" = ?',
        (new_start.date(), new_start.time(), new_end.time(), visit_id),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    # Column names and sample rows already confirmed real -- this now
    # exercises the actual normalized readers used by sync.py, so you
    # can see the real, final shape before it touches the databases.
    print("=== read_patients_normalized() ===")
    patients = read_patients_normalized()
    print(f"{len(patients)} real patients")
    for row in patients[:3]:
        print(row)

    print("\n=== read_providers_normalized() ===")
    providers = read_providers_normalized()
    print(f"{len(providers)} bookable providers")
    for row in providers:
        print(row)

    print("\n=== read_appointments_normalized() ===")
    appts = read_appointments_normalized()
    print(f"{len(appts)} real appointments")
    for row in appts[:3]:
        print(row)
