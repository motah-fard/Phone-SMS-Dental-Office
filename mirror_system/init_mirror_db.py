"""
Two DELIBERATELY SEPARATE databases:

  mirror.db          -> schedule data keyed by pseudonymous patient_id only.
                         This is what the AI call/text agent reads and writes.
                         Contains no name, phone, DOB, or anything else that
                         identifies a person on its own.

  identity_lookup.db  -> the ONLY place patient_id maps back to a real person
                         (name, phone, DOB, and the source-system patient id
                         needed for write-back). In production this should
                         sit behind its own access controls/audit logging,
                         separate from anything the AI conversation layer
                         can reach directly.
"""
import sqlite3
from pathlib import Path

MIRROR_DB_PATH = Path(__file__).parent / "mirror.db"
LOOKUP_DB_PATH = Path(__file__).parent / "identity_lookup.db"


def init_mirror_db():
    if MIRROR_DB_PATH.exists():
        MIRROR_DB_PATH.unlink()

    conn = sqlite3.connect(MIRROR_DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE providers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            work_start TEXT NOT NULL,
            work_end TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE appointments (
            id INTEGER PRIMARY KEY,
            patient_id TEXT NOT NULL,
            provider_id INTEGER NOT NULL REFERENCES providers(id),
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            status TEXT NOT NULL,
            appt_type TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    print(f"Mirror (pseudonymized) DB created at {MIRROR_DB_PATH}")


def init_lookup_db():
    if LOOKUP_DB_PATH.exists():
        LOOKUP_DB_PATH.unlink()

    conn = sqlite3.connect(LOOKUP_DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE identity_map (
            patient_id TEXT PRIMARY KEY,
            source_patient_id INTEGER NOT NULL UNIQUE,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            dob TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    print(f"Identity lookup DB created at {LOOKUP_DB_PATH}")


if __name__ == "__main__":
    init_mirror_db()
    init_lookup_db()
