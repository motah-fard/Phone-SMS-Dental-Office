"""scripts/availability.py -- slot computation, weekend closure, and
multi-provider search."""
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import availability


def next_weekday(start: datetime, target_weekday: int) -> datetime:
    """target_weekday: 0=Mon ... 5=Sat, 6=Sun"""
    days_ahead = (target_weekday - start.weekday()) % 7
    days_ahead = days_ahead or 7
    return start + timedelta(days=days_ahead)


def test_get_open_slots_on_a_weekday_returns_slots(fresh_db):
    monday = next_weekday(datetime.now(), 0).replace(hour=0, minute=0, second=0, microsecond=0)
    slots = availability.get_open_slots(provider_id=1, day=monday)
    assert len(slots) > 0
    for start, end in slots:
        assert (end - start).total_seconds() == 30 * 60


def test_get_open_slots_on_saturday_is_always_empty(fresh_db):
    saturday = next_weekday(datetime.now(), 5)
    assert availability.get_open_slots(provider_id=1, day=saturday) == []


def test_get_open_slots_on_sunday_is_always_empty(fresh_db):
    sunday = next_weekday(datetime.now(), 6)
    assert availability.get_open_slots(provider_id=1, day=sunday) == []


def test_get_open_slots_unknown_provider_raises_value_error(fresh_db):
    monday = next_weekday(datetime.now(), 0)
    with pytest.raises(ValueError):
        availability.get_open_slots(provider_id=9999, day=monday)


def test_get_open_slots_excludes_busy_times(fresh_db):
    """Patient 1's seeded cleaning appointment with provider 1 should
    make that exact slot unavailable."""
    import sqlite3
    conn = sqlite3.connect(availability.MIRROR_DB)
    row = conn.execute(
        "SELECT provider_id, start_time, end_time FROM appointments WHERE patient_id = 'PT-0001'"
    ).fetchone()
    conn.close()
    provider_id, start_str, end_str = row
    booked_start = datetime.fromisoformat(start_str)
    day = booked_start.replace(hour=0, minute=0, second=0, microsecond=0)

    slots = availability.get_open_slots(provider_id, day)
    for s, e in slots:
        assert not (s < datetime.fromisoformat(end_str) and e > booked_start)


def test_find_soonest_slots_skips_weekend(fresh_db):
    friday = next_weekday(datetime.now(), 4).replace(hour=0, minute=0, second=0, microsecond=0)
    slots = availability.find_soonest_slots(provider_id=2, start_from=friday, max_days_ahead=5)
    for s, e in slots:
        assert s.weekday() < 5


def test_find_soonest_slots_returns_empty_when_nothing_within_window(fresh_db):
    monday = next_weekday(datetime.now(), 0)
    slots = availability.find_soonest_slots(provider_id=1, start_from=monday, max_days_ahead=0)
    assert slots == []


def test_list_providers_returns_seeded_providers(fresh_db):
    providers = availability.list_providers()
    names = {p["name"] for p in providers}
    assert "Dr. Lee" in names and "Dr. Patel" in names


def test_find_soonest_slots_any_provider_returns_a_provider_and_slots(fresh_db):
    tomorrow = datetime.now() + timedelta(days=1)
    provider, slots = availability.find_soonest_slots_any_provider(tomorrow)
    assert provider is not None
    assert len(slots) > 0
    assert provider["provider_id"] in {1, 2}


def test_find_soonest_slots_any_provider_none_when_window_too_short(fresh_db):
    # Start the search on a Saturday with a 1-day window -- Saturday is
    # closed, so there's no open day inside the window at all.
    saturday = next_weekday(datetime.now(), 5)
    provider, slots = availability.find_soonest_slots_any_provider(saturday, max_days_ahead=1)
    assert provider is None
    assert slots == []


def test_get_open_slots_raises_availability_error_on_db_failure(fresh_db, monkeypatch):
    monkeypatch.setattr(availability, "MIRROR_DB", Path("/nonexistent_dir_xyz_12345/mirror.db"))
    monday = next_weekday(datetime.now(), 0)
    with pytest.raises(availability.AvailabilityError):
        availability.get_open_slots(provider_id=1, day=monday)


def test_list_providers_raises_availability_error_on_db_failure(fresh_db, monkeypatch):
    monkeypatch.setattr(availability, "MIRROR_DB", Path("/nonexistent_dir_xyz_12345/mirror.db"))
    with pytest.raises(availability.AvailabilityError):
        availability.list_providers()
