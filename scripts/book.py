"""
Channel-agnostic booking logic. Voice and SMS both call these same
functions — neither channel should have its own copy of this logic.

Identity resolution (phone -> patient_id) is the ONLY step that touches
identity_lookup.db. Everything after that works purely in pseudonymous
patient_id terms against mirror.db, then writes back to source.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

from availability import get_open_slots

SOURCE_DB = Path(__file__).parent.parent / "source_system" / "practiceworks_sim.db"
MIRROR_DB = Path(__file__).parent.parent / "mirror_system" / "mirror.db"
LOOKUP_DB = Path(__file__).parent.parent / "mirror_system" / "identity_lookup.db"


def resolve_patient_by_phone(phone: str):
    conn = sqlite3.connect(LOOKUP_DB)
    cur = conn.cursor()
    cur.execute(
        "SELECT patient_id, first_name, source_patient_id FROM identity_map WHERE phone = ?",
        (phone,),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    patient_id, first_name, source_patient_id = row
    return {"patient_id": patient_id, "first_name": first_name, "source_patient_id": source_patient_id}


def get_upcoming_appointments(patient_id: str):
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


def reschedule_appointment(appointment_id: int, new_start: datetime, new_end: datetime, source_patient_id: int):
    """Updates mirror first, then writes the same change back to source.
    In production this write-back is the step that needs the confirmed
    PracticeWorks integration mechanism (ODBC write vs. API call)."""
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


if __name__ == "__main__":
    patient = resolve_patient_by_phone("+15551230001")
    print("Resolved patient:", patient)
    print("Upcoming appointments:", get_upcoming_appointments(patient["patient_id"]))
