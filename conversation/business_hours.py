"""
Dental Arts Practice hours: Monday-Friday 8am-5pm Pacific, closed
Saturday and Sunday. Single source of truth for two separate things
that both need it:

1. Whether "talk to a live person" can ever be offered (voice and SMS
   escalation both check this -- never promise a transfer when no one
   would pick up).
2. Whether a day has any appointment availability at all (availability.py
   uses this to skip weekends entirely, before even checking a
   provider's own work_start/work_end).

Change the hours here once if they ever change -- nothing else should
hardcode a day-of-week check or an 8/5 boundary.
"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

OFFICE_TZ = ZoneInfo("America/Los_Angeles")
OPEN_TIME = time(8, 0)
CLOSE_TIME = time(17, 0)
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _localize(dt: datetime | None) -> datetime:
    dt = dt or datetime.now(OFFICE_TZ)
    return dt.astimezone(OFFICE_TZ) if dt.tzinfo else dt.replace(tzinfo=OFFICE_TZ)


def is_open_day(dt: datetime | None = None) -> bool:
    """Whether the office is open at all on this date -- ignores time of
    day. Used by availability.py so weekends never show open slots."""
    return _localize(dt).weekday() < 5


def is_staffed(dt: datetime | None = None) -> bool:
    """Whether a live person could actually pick up right now. Weekdays
    8am-5pm only -- never true outside that, including weekends."""
    dt = _localize(dt)
    return is_open_day(dt) and OPEN_TIME <= dt.time() < CLOSE_TIME


def next_staffed_description(dt: datetime | None = None) -> str:
    """A natural phrase for when staff will next be available, for
    after-hours messaging -- never a bare timestamp, and never implies
    someone is there now when they aren't."""
    dt = _localize(dt)
    if is_staffed(dt):
        return "right now"
    if is_open_day(dt) and dt.time() < OPEN_TIME:
        return "later this morning at 8am"

    candidate = dt + timedelta(days=1)
    while not is_open_day(candidate):
        candidate += timedelta(days=1)

    # "Tomorrow" only reads as clear when today is itself a weekday --
    # from a weekend, always name the day (e.g. "Monday"), since "the
    # office is closed, but we'll call tomorrow" on a Sunday is
    # technically true but needlessly confusing next to "Monday."
    if is_open_day(dt) and candidate.date() == (dt + timedelta(days=1)).date():
        return "tomorrow morning at 8am"
    return f"{WEEKDAY_NAMES[candidate.weekday()]} morning at 8am"
