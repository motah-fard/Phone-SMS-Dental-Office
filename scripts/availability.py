"""
Computes open slots for a provider on a given day, from the mirror DB only
(never touches identity_lookup — availability doesn't need to know who
anyone is).
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

MIRROR_DB = Path(__file__).parent.parent / "mirror_system" / "mirror.db"

SLOT_MINUTES = 30


def get_open_slots(provider_id: int, day: datetime, duration_minutes: int = SLOT_MINUTES):
    conn = sqlite3.connect(MIRROR_DB)
    cur = conn.cursor()

    cur.execute("SELECT work_start, work_end FROM providers WHERE id = ?", (provider_id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        raise ValueError(f"Unknown provider_id {provider_id}")
    work_start, work_end = row

    day_start = day.replace(
        hour=int(work_start.split(":")[0]), minute=int(work_start.split(":")[1]),
        second=0, microsecond=0,
    )
    day_end = day.replace(
        hour=int(work_end.split(":")[0]), minute=int(work_end.split(":")[1]),
        second=0, microsecond=0,
    )

    cur.execute(
        """
        SELECT start_time, end_time FROM appointments
        WHERE provider_id = ? AND status != 'cancelled'
          AND date(start_time) = date(?)
        ORDER BY start_time
        """,
        (provider_id, day.isoformat()),
    )
    busy = [(datetime.fromisoformat(s), datetime.fromisoformat(e)) for s, e in cur.fetchall()]
    conn.close()

    slots = []
    cursor = day_start
    delta = timedelta(minutes=duration_minutes)
    while cursor + delta <= day_end:
        slot_end = cursor + delta
        overlaps = any(cursor < b_end and slot_end > b_start for b_start, b_end in busy)
        if not overlaps:
            slots.append((cursor, slot_end))
        cursor += delta

    return slots


if __name__ == "__main__":
    slots = get_open_slots(provider_id=1, day=datetime.now() + timedelta(days=2))
    for s, e in slots:
        print(f"{s.strftime('%Y-%m-%d %H:%M')} - {e.strftime('%H:%M')}")
