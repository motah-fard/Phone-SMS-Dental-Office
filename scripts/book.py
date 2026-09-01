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

Every function raises SchedulingError (never a raw sqlite3.Error) on a
database problem, after logging the failure. Callers (sms_conversation.py,
webhook_server.py) catch SchedulingError once at their own boundary and
show a warm fallback message -- see handle_inbound_sms's try/except.
"""
import os
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "mirror_system"))

from availability import get_open_slots, find_soonest_slots
from audit_log import log_access

SOURCE_DB = Path(__file__).parent.parent / "source_system" / "practiceworks_sim.db"
MIRROR_DB = Path(__file__).parent.parent / "mirror_system" / "mirror.db"
LOOKUP_DB = Path(__file__).parent.parent / "mirror_system" / "identity_lookup.db"

# "sqlite" (default) writes reschedules back to the fake simulated
# source_system database. "pervasive" writes back to the real
# PracticeWorks database via source_system/pervasive_odbc_source.py.
# Same pattern as LLM_PROVIDER in sms_conversation.py -- callers of
# reschedule_appointment() never need to know or care which backend is
# active, only this one env var changes.
SOURCE_BACKEND = os.environ.get("SOURCE_BACKEND", "sqlite").lower()


class SchedulingError(Exception):
    """Raised whenever a database operation in this module fails. Always
    raised with the original error already logged via audit_log, so
    catching this and showing a warm fallback message doesn't lose the
    underlying cause -- it's still in the audit log for debugging."""


def resolve_patient_by_phone(phone: str, actor: str = "unknown"):
    """Phone-only lookup. This is NOT sufficient identity verification for
    an inbound caller/texter claiming to be a patient -- caller ID can be
    spoofed, and a phone can belong to a family member or a lost/stolen
    device. Use this only for system-initiated contact where WE are
    reaching out to a number already on file (e.g. sending a reminder),
    never to authenticate someone claiming to be a patient. For that,
    use verify_patient() below."""
    try:
        conn = sqlite3.connect(LOOKUP_DB)
        cur = conn.cursor()
        cur.execute(
            "SELECT patient_id, first_name, source_patient_id FROM identity_map WHERE phone = ?",
            (phone,),
        )
        row = cur.fetchone()
        conn.close()
    except sqlite3.Error as e:
        log_access(actor, "resolve_patient_by_phone", success=False, detail=f"db error: {e}")
        raise SchedulingError("could not look up patient record") from e

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
    try:
        conn = sqlite3.connect(LOOKUP_DB)
        cur = conn.cursor()
        cur.execute(
            "SELECT patient_id, first_name, source_patient_id FROM identity_map WHERE phone = ? AND dob = ?",
            (phone, dob),
        )
        row = cur.fetchone()
        conn.close()
    except sqlite3.Error as e:
        log_access(actor, "verify_patient", success=False, detail=f"db error: {e}")
        raise SchedulingError("could not verify patient") from e

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
    """Only truly future appointments -- this never mattered against
    our own fake seed data (always constructed as "today + a few days"),
    but real PracticeWorks data includes years of appointment HISTORY,
    and a patient's most recent past visit would otherwise sort in
    right alongside anything actually upcoming. ISO 8601 strings compare
    correctly as plain strings, so no datetime parsing needed here."""
    try:
        now_iso = datetime.now().isoformat()
        conn = sqlite3.connect(MIRROR_DB)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT a.id, a.provider_id, p.name, a.start_time, a.end_time, a.status, a.appt_type
            FROM appointments a JOIN providers p ON p.id = a.provider_id
            WHERE a.patient_id = ? AND a.status != 'cancelled' AND a.start_time >= ?
            ORDER BY a.start_time
            """,
            (patient_id, now_iso),
        )
        rows = cur.fetchall()
        conn.close()
    except sqlite3.Error as e:
        log_access(actor, "get_upcoming_appointments", patient_id=patient_id, success=False, detail=f"db error: {e}")
        raise SchedulingError("could not read appointments") from e

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
    pass it when the caller already has it, e.g. from verify_patient.

    KNOWN LIMITATION: the mirror write and the source write are two
    separate commits, not one atomic transaction across two database
    engines. If the mirror update succeeds but the source write then
    fails, they'll disagree until the next sync -- this is flagged
    below rather than silently ignored, but resolving it properly
    (a reconciliation pass, or a real distributed-transaction approach)
    is a before-go-live item, not solved here."""
    try:
        mirror = sqlite3.connect(MIRROR_DB)
        mirror.execute(
            "UPDATE appointments SET start_time = ?, end_time = ?, status = 'confirmed' WHERE id = ?",
            (new_start.isoformat(), new_end.isoformat(), appointment_id),
        )
        mirror.commit()
        mirror.close()
    except sqlite3.Error as e:
        log_access(actor, "reschedule_appointment", patient_id=patient_id, success=False, detail=f"mirror write failed: {e}")
        raise SchedulingError("could not update appointment") from e

    try:
        if SOURCE_BACKEND == "pervasive":
            # Real write-back, reschedule (UPDATE) only -- new-appointment
            # (INSERT) creation against Pervasive isn't built yet, see
            # pervasive_odbc_source.py's comment on why that's riskier.
            sys.path.insert(0, str(Path(__file__).parent.parent / "source_system"))
            from pervasive_odbc_source import write_reschedule
            write_reschedule(appointment_id, new_start, new_end)
        else:
            src = sqlite3.connect(SOURCE_DB)
            src.execute(
                "UPDATE appointments SET start_time = ?, end_time = ?, status = 'confirmed' WHERE id = ? AND patient_id = ?",
                (new_start.isoformat(), new_end.isoformat(), appointment_id, source_patient_id),
            )
            src.commit()
            src.close()
    except Exception as e:
        # Broad except here on purpose: this branch runs either sqlite3
        # calls or pyodbc calls depending on SOURCE_BACKEND, and both
        # need to land in the same SchedulingError wrapping -- pyodbc
        # isn't imported at module level (it's not installed on most
        # machines), so its exception type can't be named directly here.
        log_access(
            actor, "reschedule_appointment", patient_id=patient_id, success=False,
            detail=f"MIRROR UPDATED BUT SOURCE WRITE FAILED (out of sync until next reconciliation): {e}",
        )
        raise SchedulingError("appointment updated locally but the source system write failed") from e

    log_access(
        actor, "reschedule_appointment", patient_id=patient_id,
        detail=f"appointment {appointment_id} -> {new_start.isoformat()}",
    )


def book_new_appointment(
    patient_id: str,
    source_patient_id: int,
    provider_id: int,
    start: datetime,
    end: datetime,
    appt_type: str = "New Appointment",
    actor: str = "unknown",
):
    """Creates a brand new appointment, as opposed to reschedule_appointment
    which moves an existing one.

    SOURCE_BACKEND="pervasive" writes to the real source FIRST (it
    generates the real Visit ID), then mirrors that same id locally --
    the reverse order from the sqlite path below. This is deliberate:
    if the source insert succeeds but the mirror insert then fails, the
    real appointment already exists in PracticeWorks and the next
    sync_from_pervasive() will pick it up naturally -- a more forgiving
    failure mode than reschedule's, which needs explicit reconciliation
    if mirror and source disagree."""
    if SOURCE_BACKEND == "pervasive":
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent / "source_system"))
            from pervasive_odbc_source import write_new_appointment
            new_id = write_new_appointment(source_patient_id, provider_id, start, end, appt_type)
        except Exception as e:
            log_access(actor, "book_new_appointment", patient_id=patient_id, success=False, detail=f"pervasive insert failed: {e}")
            raise SchedulingError("could not book appointment") from e
    else:
        try:
            mirror_conn = sqlite3.connect(MIRROR_DB)
            mirror_max = mirror_conn.execute("SELECT COALESCE(MAX(id), 0) FROM appointments").fetchone()[0]
            mirror_conn.close()

            src_conn = sqlite3.connect(SOURCE_DB)
            src_max = src_conn.execute("SELECT COALESCE(MAX(id), 0) FROM appointments").fetchone()[0]
            src_conn.close()

            new_id = max(mirror_max, src_max) + 1
        except sqlite3.Error as e:
            log_access(actor, "book_new_appointment", patient_id=patient_id, success=False, detail=f"id generation failed: {e}")
            raise SchedulingError("could not book appointment") from e

        try:
            src = sqlite3.connect(SOURCE_DB)
            src.execute(
                "INSERT INTO appointments VALUES (?, ?, ?, ?, ?, 'confirmed', ?)",
                (new_id, source_patient_id, provider_id, start.isoformat(), end.isoformat(), appt_type),
            )
            src.commit()
            src.close()
        except sqlite3.Error as e:
            log_access(actor, "book_new_appointment", patient_id=patient_id, success=False, detail=f"source insert failed: {e}")
            raise SchedulingError("could not book appointment") from e

    try:
        mirror = sqlite3.connect(MIRROR_DB)
        mirror.execute(
            "INSERT INTO appointments VALUES (?, ?, ?, ?, ?, 'confirmed', ?)",
            (new_id, patient_id, provider_id, start.isoformat(), end.isoformat(), appt_type),
        )
        mirror.commit()
        mirror.close()
    except sqlite3.Error as e:
        log_access(
            actor, "book_new_appointment", patient_id=patient_id, success=False,
            detail=f"SOURCE BOOKED BUT MIRROR INSERT FAILED (will self-heal on next sync): {e}",
        )
        raise SchedulingError("appointment booked in the source system but the local mirror update failed") from e

    log_access(actor, "book_new_appointment", patient_id=patient_id, detail=f"appointment {new_id} at {start.isoformat()}")
    return new_id


if __name__ == "__main__":
    patient = resolve_patient_by_phone("+15551230001", actor="book_py_manual_run")
    print("Resolved patient:", patient)
    print("Upcoming appointments:", get_upcoming_appointments(patient["patient_id"], actor="book_py_manual_run"))
