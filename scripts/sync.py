"""
One-way sync: source (simulated PracticeWorks) -> mirror + identity_lookup.

Real version will replace `read_source_*` with ODBC/API calls once the
actual PracticeWorks integration mechanism is confirmed. Everything
downstream (availability, booking) only depends on the mirror/lookup
schemas, not on how the source is read.
"""
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "mirror_system"))
from audit_log import log_access

SOURCE_DB = Path(__file__).parent.parent / "source_system" / "practiceworks_sim.db"
MIRROR_DB = Path(__file__).parent.parent / "mirror_system" / "mirror.db"
LOOKUP_DB = Path(__file__).parent.parent / "mirror_system" / "identity_lookup.db"


class SyncError(Exception):
    """Raised when the sync fails partway -- always after the failure is
    logged via audit_log, so it's visible in scripts/view_audit_log.py
    even if this exception is only caught and printed by a caller."""


def next_patient_id(cur):
    cur.execute("SELECT patient_id FROM identity_map ORDER BY patient_id DESC LIMIT 1")
    row = cur.fetchone()
    if row is None:
        return "PT-0001"
    n = int(row[0].split("-")[1]) + 1
    return f"PT-{n:04d}"


def sync():
    src = mirror = lookup = None
    try:
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

        new_identities = 0
        for row in src_cur.execute("SELECT id, first_name, last_name, dob, phone FROM patients"):
            src_id, first, last, dob, phone = row
            if src_id not in source_to_pseudo:
                pid = next_patient_id(lookup_cur)
                lookup_cur.execute(
                    "INSERT INTO identity_map VALUES (?, ?, ?, ?, ?, ?)",
                    (pid, src_id, first, last, phone, dob),
                )
                source_to_pseudo[src_id] = pid
                new_identities += 1

        lookup.commit()

        # --- appointments: map to pseudonymous patient_id, no PHI carried over ---
        mirror_cur.execute("DELETE FROM appointments")
        synced_appointments = 0
        for row in src_cur.execute(
            "SELECT id, patient_id, provider_id, start_time, end_time, status, appt_type FROM appointments"
        ):
            appt_id, src_patient_id, provider_id, start, end, status, appt_type = row
            if src_patient_id not in source_to_pseudo:
                # Shouldn't happen -- every appointment's patient was just
                # synced above -- but skip rather than crash the whole
                # sync if source data is ever inconsistent.
                log_access("sync_job", "sync_source_to_mirror", success=False,
                           detail=f"appointment {appt_id} references unknown patient {src_patient_id}, skipped")
                continue
            pseudo_id = source_to_pseudo[src_patient_id]
            mirror_cur.execute(
                "INSERT INTO appointments VALUES (?, ?, ?, ?, ?, ?, ?)",
                (appt_id, pseudo_id, provider_id, start, end, status, appt_type),
            )
            synced_appointments += 1

        mirror.commit()

    except sqlite3.Error as e:
        log_access("sync_job", "sync_source_to_mirror", success=False, detail=f"sync failed: {e}")
        raise SyncError(f"sync failed: {e}") from e
    finally:
        for conn in (src, mirror, lookup):
            if conn is not None:
                conn.close()

    log_access(
        "sync_job", "sync_source_to_mirror",
        detail=f"{new_identities} new identity mapping(s), {synced_appointments} appointment(s) synced",
    )
    print("Sync complete: source -> mirror + identity_lookup")


if __name__ == "__main__":
    sync()
