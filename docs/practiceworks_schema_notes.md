# PracticeWorks (Pervasive PSQL) schema notes

Captured from the `TUTOR` database (PracticeWorks' built-in training/demo
database — synthetic data, safe to browse). Connection is via Pervasive
PSQL / Btrieve ODBC. The live production database is `PWORKS` — same
schema, real patient data, do not connect anything here to it yet.

Databases seen on the server: `DEFAULTDB` (system catalog), `DEMODATA`
(generic PSQL sample, unrelated to PracticeWorks), `PW`, `PWORKS` (live),
`TEMPDB`, `TUTOR` (training data — what we're using to build against).

## Tables relevant to scheduling (confirmed to exist, columns TBD)

| Real table name | Our guess at purpose | Maps to |
|---|---|---|
| `Patient File` | Patient demographics | `source_system.patients` |
| `Appointments` | Appointment records | `source_system.appointments` |
| `Appointment books` | Per-provider/operatory calendar | provider scheduling grid |
| `Appt Book Exceptions` | Blocked-off time / exceptions | availability calc |
| `Appt Book Multi User` | Multi-user scheduling config | probably irrelevant to us |
| `Open Close Times` | Practice/provider working hours | `providers.work_start/work_end` |
| `Employee list` | Staff, likely includes providers | `source_system.providers` |
| `Locations` | Practice location(s) | only relevant if multi-location |
| `Resource Definitions` | Operatories/chairs/equipment | only if we need per-chair booking |
| `Recall Contact Roster` | Recall/reminder contact list | future messaging/recall feature |
| `FollowUpContact` | Follow-up contact tracking | future messaging feature |
| `Practice Info` | Practice-level settings | reference only |

## Still needed before wiring up the real adapter

Column names for at minimum `Patient File` and `Appointments` — table
names are confirmed, fields are not. Since this is the training DB with
fake data, it's safe to actually open **View Data** on these two tables
(no real PHI at risk here, unlike `PWORKS`) to get both the column names
and a sense of real value formats (date format, status codes, ID types).

Once we have those, `source_system/pervasive_odbc_source.py` gets filled
in to replace the SQLite simulation — same downstream interface
(`sync.py`, `book.py`, `availability.py` don't change).

Note: table names contain spaces, so ODBC queries need to quote them,
e.g. `SELECT * FROM "Patient File"` (exact quoting syntax depends on the
Pervasive ODBC driver — confirm once we're querying for real).
