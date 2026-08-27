"""Pure functions, no database needed -- covers every branch directly."""
from datetime import datetime
from zoneinfo import ZoneInfo

from business_hours import is_open_day, is_staffed, next_staffed_description

TZ = ZoneInfo("America/Los_Angeles")


def dt(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def test_is_open_day_weekdays_true():
    for day in range(24, 29):  # Mon Aug 24 -- Fri Aug 28, 2026
        assert is_open_day(dt(2026, 8, day, 12)) is True


def test_is_open_day_weekend_false():
    assert is_open_day(dt(2026, 8, 29, 12)) is False  # Saturday
    assert is_open_day(dt(2026, 8, 30, 12)) is False  # Sunday


def test_is_staffed_within_hours():
    assert is_staffed(dt(2026, 8, 27, 14, 0)) is True  # Thursday 2pm


def test_is_staffed_exact_boundaries():
    assert is_staffed(dt(2026, 8, 27, 8, 0)) is True   # opens at 8:00 inclusive
    assert is_staffed(dt(2026, 8, 27, 16, 59)) is True
    assert is_staffed(dt(2026, 8, 27, 17, 0)) is False  # closes at 17:00 exclusive
    assert is_staffed(dt(2026, 8, 27, 7, 59)) is False


def test_is_staffed_false_on_weekend_regardless_of_time():
    assert is_staffed(dt(2026, 8, 29, 12, 0)) is False


def test_next_staffed_description_currently_staffed():
    assert next_staffed_description(dt(2026, 8, 27, 14, 0)) == "right now"


def test_next_staffed_description_before_open_same_day():
    assert next_staffed_description(dt(2026, 8, 27, 6, 0)) == "later this morning at 8am"


def test_next_staffed_description_weekday_evening():
    assert next_staffed_description(dt(2026, 8, 27, 21, 0)) == "tomorrow morning at 8am"


def test_next_staffed_description_friday_evening_skips_to_monday():
    assert next_staffed_description(dt(2026, 8, 28, 18, 0)) == "Monday morning at 8am"


def test_next_staffed_description_saturday():
    assert next_staffed_description(dt(2026, 8, 29, 12, 0)) == "Monday morning at 8am"


def test_next_staffed_description_sunday_says_monday_not_tomorrow():
    """Regression test for a real bug found during manual testing --
    Sunday used to say "tomorrow morning," which is technically true but
    confusing right next to "Monday" being the actual day name."""
    assert next_staffed_description(dt(2026, 8, 30, 12, 0)) == "Monday morning at 8am"


def test_next_staffed_description_naive_datetime_gets_localized():
    """No tzinfo -- should be treated as already being in the office
    timezone rather than raising."""
    naive = datetime(2026, 8, 27, 14, 0)
    assert next_staffed_description(naive) == "right now"
