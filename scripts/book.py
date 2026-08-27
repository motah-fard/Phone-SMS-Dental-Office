"""
Channel-agnostic booking logic. Voice and SMS both call these same
functions — neither channel should have its own copy of this logic.

Identity resolution (phone -> patient_id) is the ONLY step that touches
identity_lookup.db. Everything after that works purely in pseudonymous
patient_id terms against mirror.db, then writes back to source.

Every function here takes an `actor` string identifying which channel
called it (e.g. "sms_webhook", "voice_tool:reschedule_appointment") and
logs the access via mirror_system/audit_log.py. This is the single
instrumentation point for both channels -- add a new channel and its
audit trail comes for free, no separate logging to wire up.
"""
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "mirror_system"))

from availability import get_open_slots
from audit_log import log_access

SOURCE_DB = Path(__file__).parent.parent / "source_system" / "practiceworks_sim.db"
MIRROR_DB = Path(__file__).parent.parent / "mirror_system" / "mirror.db"
LOOKUP_DB = Path(__file__).parent.parent / "mirror_system" / "identity_lookup.db"


def resolve_patient_by_phone(phone: str, actor: str = "unknown"):
    """Phone-only lookup. This is NOT sufficient identity verification for
    an inbound caller/texter claiming to be a patient -- caller ID can be
    spoofed, and a phone can belong to a family member or a lost/stolen
    device. Use this only for system-initiated contact where WE are
    reaching out to a number already on file (e.g. sending a reminder),
    never to authenticate someone claiming to be a patient. For that,
    use verify_patient() below."""
    conn = sqlite3.connect(LOOKUP_DB)
    cur = conn.cursor()
    cur.execute(
        "SELECT patient_id, first_name, source_patient_id FROM identity_map WHERE phone = ?",
        (phone,),
    )
    row = cur.fetchone()
    conn.close()

    if row is None:
        log_access(actor, "resolve_patient_by_phone", detail=f"no match for phone ending {phone[-4:]}", success=False)
        return None

    patient_id, first_name, source_patient_id = row
    log_access(actor, "resolve_patient_by_phone", patient_id=patient_id)
    return {"patient_id": patient_id, "first_name": first_name, "source_patient_id": source_patient_id}


def verify_patient(phone: str, dob: str, actor: str = "unknown"):
    """Two-factor identity verification for anyone calling/texting in and
    claiming to be a patient -- phone number plus date of birth, per
    standard HIPAA call-center guidance (two independent identifiers,
    never caller ID alone). `dob` must already be normalized to
    'YYYY-MM-DD' -- see parse_dob().

    Required before disclosing or changing appointment data in response
    to anything an inbound caller/texter asked for. Not required for
    resolve_patient_by_phone's system-initiated use case above."""
    conn = sqlite3.connect(LOOKUP_DB)
    cur = conn.cursor()
    cur.execute(
        "SELECT patient_id, first_name, source_patient_id FROM identity_map WHERE phone = ? AND dob = ?",
        (phone, dob),
    )
    row = cur.fetchone()
    conn.close()

    if row is None:
        log_access(actor, "verify_patient", detail=f"failed verification, phone ending {phone[-4:]}", success=False)
        return None

    patient_id, first_name, source_patient_id = row
    log_access(actor, "verify_patient", patient_id=patient_id)
    return {"patient_id": patient_id, "first_name": first_name, "source_patient_id": source_patient_id}


def parse_dob(text: str) -> str | None:
    """Normalizes a spoken/typed date of birth into 'YYYY-MM-DD' to match
    identity_lookup's storage format. Returns None if it doesn't look
    like a date at all -- callers should treat that as "ask again",
    not as a failed verification (those are different failure modes:
    one is "I couldn't understand you," the other is "that doesn't
    match our records")."""
    text = text.strip()
    for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def get_upcoming_appointments(patient_id: str, actor: str = "unknown"):
    conn = sqlite3.connect(MIRROR_DB)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT a.id, a.provider_id, p.name, a.start_time, a.end_time, a.status, a.appt_type
        FROM appointments a JOIN providers p ON p.id = a.provider_id
        WHERE a.patient_id = ? AND a.status != 'cancelled'
        ORDER BY a.start_time
        """,
        (patient_id,),
    )
    rows = cur.fetchall()
    conn.close()

    log_access(actor, "get_upcoming_appointments", patient_id=patient_id, detail=f"{len(rows)} appointment(s)")
    return [
        {
            "appointment_id": r[0],
            "provider_id": r[1],
            "provider_name": r[2],
            "start_time": r[3],
            "end_time": r[4],
            "status": r[5],
            "appt_type": r[6],
        }
        for r in rows
    ]


def reschedule_appointment(
    appointment_id: int,
    new_start: datetime,
    new_end: datetime,
    source_patient_id: int,
    actor: str = "unknown",
    patient_id: str | None = None,
):
    """Updates mirror first, then writes the same change back to source.
    In production this write-back is the step that needs the confirmed
    PracticeWorks integration mechanism (ODBC write vs. API call).

    `patient_id` here is only for the audit log (the pseudonymous id,
    not `source_patient_id` which is PracticeWorks' internal key) --
    pass it when the caller already has it, e.g. from resolve_patient_by_phone."""
    mirror = sqlite3.connect(MIRROR_DB)
    mirror.execute(
        "UPDATE appointments SET start_time = ?, end_time = ?, status = 'confirmed' WHERE id = ?",
        (new_start.isoformat(), new_end.isoformat(), appointment_id),
    )
    mirror.commit()
    mirror.close()

    src = sqlite3.connect(SOURCE_DB)
    src.execute(
        "UPDATE appointments SET start_time = ?, end_time = ?, status = 'confirmed' WHERE id = ? AND patient_id = ?",
        (new_start.isoformat(), new_end.isoformat(), appointment_id, source_patient_id),
    )
    src.commit()
    src.close()

    log_access(
        actor, "reschedule_appointment", patient_id=patient_id,
        detail=f"appointment {appointment_id} -> {new_start.isoformat()}",
    )


if __name__ == "__main__":
    patient = resolve_patient_by_phone("+15551230001", actor="book_py_manual_run")
    print("Resolved patient:", patient)
    print("Upcoming appointments:", get_upcoming_appointments(patient["patient_id"], actor="book_py_manual_run"))
