"""
One-way sync: source (simulated PracticeWorks) -> mirror + identity_lookup.

Real version will replace `read_source_*` with ODBC/API calls once the
actual PracticeWorks integration mechanism is confirmed. Everything
downstream (availability, booking) only depends on the mirror/lookup
schemas, not on how the source is read.
"""
import sqlite3
from pathlib import Path

SOURCE_DB = Path(__file__).parent.parent / "source_system" / "practiceworks_sim.db"
MIRROR_DB = Path(__file__).parent.parent / "mirror_system" / "mirror.db"
LOOKUP_DB = Path(__file__).parent.parent / "mirror_system" / "identity_lookup.db"


def next_patient_id(cur):
    cur.execute("SELECT patient_id FROM identity_map ORDER BY patient_id DESC LIMIT 1")
    row = cur.fetchone()
    if row is None:
        return "PT-0001"
    n = int(row[0].split("-")[1]) + 1
    return f"PT-{n:04d}"


def sync():
    src = sqlite3.connect(SOURCE_DB)
    mirror = sqlite3.connect(MIRROR_DB)
    lookup = sqlite3.connect(LOOKUP_DB)

    src_cur = src.cursor()
    mirror_cur = mirror.cursor()
    lookup_cur = lookup.cursor()

    # --- providers: not PHI, copy straight across ---
    mirror_cur.execute("DELETE FROM providers")
    for row in src_cur.execute("SELECT id, name, work_start, work_end FROM providers"):
        mirror_cur.execute("INSERT INTO providers VALUES (?, ?, ?, ?)", row)

    # --- patients: assign/reuse pseudonymous patient_id ---
    source_to_pseudo = {}
    for row in lookup_cur.execute("SELECT patient_id, source_patient_id FROM identity_map"):
        source_to_pseudo[row[1]] = row[0]

    for row in src_cur.execute("SELECT id, first_name, last_name, dob, phone FROM patients"):
        src_id, first, last, dob, phone = row
        if src_id not in source_to_pseudo:
            pid = next_patient_id(lookup_cur)
            lookup_cur.execute(
                "INSERT INTO identity_map VALUES (?, ?, ?, ?, ?, ?)",
                (pid, src_id, first, last, phone, dob),
            )
            source_to_pseudo[src_id] = pid

    lookup.commit()

    # --- appointments: map to pseudonymous patient_id, no PHI carried over ---
    mirror_cur.execute("DELETE FROM appointments")
    for row in src_cur.execute(
        "SELECT id, patient_id, provider_id, start_time, end_time, status, appt_type FROM appointments"
    ):
        appt_id, src_patient_id, provider_id, start, end, status, appt_type = row
        pseudo_id = source_to_pseudo[src_patient_id]
        mirror_cur.execute(
            "INSERT INTO appointments VALUES (?, ?, ?, ?, ?, ?, ?)",
            (appt_id, pseudo_id, provider_id, start, end, status, appt_type),
        )

    mirror.commit()
    src.close()
    mirror.close()
    lookup.close()
    print("Sync complete: source -> mirror + identity_lookup")


if __name__ == "__main__":
    sync()
