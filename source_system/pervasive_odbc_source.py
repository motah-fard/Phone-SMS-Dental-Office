"""
STUB — real PracticeWorks connector, to replace init_source_db.py's fake
SQLite database once column names are confirmed.

Connects to the Pervasive PSQL / Btrieve engine over ODBC. Point this at
the TUTOR database DSN first (training data, safe), never PWORKS until
everything here is verified correct.

See docs/practiceworks_schema_notes.md for the real table names this is
built against and what's still unconfirmed (column names).

DSN_NAME below ("Tutor_DSN") was created via the 32-bit ODBC Data
Source Administrator, using the "Pervasive ODBC Client Interface"
driver, Server Name/IP = W-SRV-VM-102, Database Name = TUTOR.

IMPORTANT: this is a 32-bit DSN (created in odbcad32.exe from
C:\\Windows\\SysWOW64\\, not the 64-bit one). A 64-bit Python
interpreter CANNOT see or use a 32-bit-only DSN, even though it shows
up fine in the 32-bit ODBC Administrator -- ODBC drivers and the
process using them must match bitness. Check your Python's bitness
before running this:

    python -c "import struct; print(struct.calcsize('P') * 8)"

If that prints 64, you need a 32-bit Python interpreter installed
specifically to run this file (a second, side-by-side install is fine
-- it doesn't replace your main Python). If it prints 32, you're already
set.

Requires: pip install pyodbc  (installed into whichever Python
interpreter's bitness matches this DSN)
"""
import pyodbc

DSN_NAME = "Tutor_DSN"


def get_connection():
    return pyodbc.connect(f"DSN={DSN_NAME};")


def read_patients():
    """TODO: replace SELECT * with real column list once confirmed from
    'Patient File'. Table name has a space -- quote it for the driver."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM "Patient File"')
    columns = [c[0] for c in cur.description]
    rows = cur.fetchall()
    conn.close()
    return columns, rows


def read_appointments():
    """TODO: replace SELECT * with real column list once confirmed from
    'Appointments'."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM "Appointments"')
    columns = [c[0] for c in cur.description]
    rows = cur.fetchall()
    conn.close()
    return columns, rows


def read_providers():
    """TODO: confirm whether provider/dentist records live in
    'Employee list' or a dedicated provider table not yet seen."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM "Employee list"')
    columns = [c[0] for c in cur.description]
    rows = cur.fetchall()
    conn.close()
    return columns, rows


def read_work_hours():
    """TODO: confirm 'Open Close Times' schema -- expected to hold
    provider or practice working hours."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM "Open Close Times"')
    columns = [c[0] for c in cur.description]
    rows = cur.fetchall()
    conn.close()
    return columns, rows


if __name__ == "__main__":
    # Quick manual check once DSN_NAME is filled in: print column names
    # only, don't dump real rows here even against TUTOR out of habit.
    for label, fn in [
        ("Patient File", read_patients),
        ("Appointments", read_appointments),
        ("Employee list", read_providers),
        ("Open Close Times", read_work_hours),
    ]:
        columns, rows = fn()
        print(f"{label}: {len(rows)} rows, columns = {columns}")
