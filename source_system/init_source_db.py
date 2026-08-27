"""
Simulates the PracticeWorks database (PW32-style: patients, providers, appointments).
Standing in for direct ODBC/DB access until the real integration mechanism is confirmed.
Swap this module out later; every downstream script only talks to this schema.
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "practiceworks_sim.db"


def init_db():
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE patients (
            id INTEGER PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            dob TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT
        )
    """)

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
            patient_id INTEGER NOT NULL REFERENCES patients(id),
            provider_id INTEGER NOT NULL REFERENCES providers(id),
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'scheduled',
            appt_type TEXT NOT NULL
        )
    """)

    providers = [
        (1, "Dr. Lee", "09:00", "17:00"),
        (2, "Dr. Patel", "08:00", "16:00"),
    ]
    cur.executemany("INSERT INTO providers VALUES (?, ?, ?, ?)", providers)

    patients = [
        (1, "Maria", "Gonzalez", "1988-04-12", "+15551230001", "maria@example.com"),
        (2, "James", "Whitfield", "1975-11-02", "+15551230002", "james@example.com"),
        (3, "Aiko", "Tanaka", "1992-07-23", "+15551230003", "aiko@example.com"),
        (4, "David", "Brooks", "2001-01-30", "+15551230004", None),
    ]
    cur.executemany("INSERT INTO patients VALUES (?, ?, ?, ?, ?, ?)", patients)

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    def dt(days, hour, minute=0):
        return (today + timedelta(days=days, hours=hour, minutes=minute)).isoformat()

    appointments = [
        (1, 1, 1, dt(2, 9, 0), dt(2, 9, 30), "scheduled", "cleaning"),
        (2, 2, 1, dt(2, 10, 0), dt(2, 10, 30), "scheduled", "checkup"),
        (3, 3, 2, dt(3, 8, 0), dt(3, 9, 0), "scheduled", "filling"),
        (4, 4, 1, dt(5, 13, 0), dt(5, 13, 30), "confirmed", "cleaning"),
    ]
    cur.executemany("INSERT INTO appointments VALUES (?, ?, ?, ?, ?, ?, ?)", appointments)

    conn.commit()
    conn.close()
    print(f"Source (simulated PracticeWorks) DB created at {DB_PATH}")


if __name__ == "__main__":
    init_db()
