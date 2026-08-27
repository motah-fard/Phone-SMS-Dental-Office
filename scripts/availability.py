"""
Computes open slots for a provider on a given day, from the mirror DB only
(never touches identity_lookup — availability doesn't need to know who
anyone is).
"""
import sys
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "conversation"))
from business_hours import is_open_day

MIRROR_DB = Path(__file__).parent.parent / "mirror_system" / "mirror.db"

SLOT_MINUTES = 30


class AvailabilityError(Exception):
    """Raised when availability can't be computed -- callers should show
    a warm fallback ("let me have the front desk check that") rather
    than crash."""


def get_open_slots(provider_id: int, day: datetime, duration_minutes: int = SLOT_MINUTES):
    if not is_open_day(day):
        return []  # closed Saturday/Sunday -- never offer weekend slots

    try:
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
    except sqlite3.Error as e:
        raise AvailabilityError(f"could not read availability: {e}") from e

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


def find_soonest_slots(provider_id: int, start_from: datetime, max_days_ahead: int = 14, limit: int = 3):
    """Scans forward day by day (skipping closed days automatically via
    get_open_slots) for the first day with any availability, for one
    specific provider. Used when rescheduling an existing appointment,
    where the provider is already known."""
    for offset in range(max_days_ahead):
        day = start_from + timedelta(days=offset)
        slots = get_open_slots(provider_id, day)
        if slots:
            return slots[:limit]
    return []


def list_providers():
    try:
        conn = sqlite3.connect(MIRROR_DB)
        rows = conn.execute("SELECT id, name FROM providers").fetchall()
        conn.close()
    except sqlite3.Error as e:
        raise AvailabilityError(f"could not list providers: {e}") from e
    return [{"provider_id": r[0], "name": r[1]} for r in rows]


def find_soonest_slots_any_provider(start_from: datetime, max_days_ahead: int = 14, limit: int = 3):
    """For booking a brand-new appointment, where there's no existing
    appointment to anchor the search to a specific provider or day.
    Returns (provider, slots) for the first provider/day combination
    with any availability, or (None, []) if nothing found in the window."""
    providers = list_providers()
    for offset in range(max_days_ahead):
        day = start_from + timedelta(days=offset)
        if not is_open_day(day):
            continue
        for provider in providers:
            slots = get_open_slots(provider["provider_id"], day)
            if slots:
                return provider, slots[:limit]
    return None, []


if __name__ == "__main__":
    slots = get_open_slots(provider_id=1, day=datetime.now() + timedelta(days=2))
    for s, e in slots:
        print(f"{s.strftime('%Y-%m-%d %H:%M')} - {e.strftime('%H:%M')}")
