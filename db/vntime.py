"""Vietnam wall-clock helpers — the ONE place the bot's time zone lives.

Brokers type and read times in Vietnam time, but the bot host runs in
another zone (Calgary). Naive datetime.now()/date.today()/.timestamp()/
fromtimestamp() all use the HOST zone, so a viewing typed as 15:00 was
stored as 15:00 Calgary (= 05:00 next day in Vietnam) and "Hôm nay" in the
date picker followed the Calgary date.

Every parse / display / "today" in bot code goes through here. Epochs in
the DB stay plain UTC seconds; only the wall-clock conversion is pinned.
"""
import datetime as _dt

try:  # tzdata may be missing on Windows
    from zoneinfo import ZoneInfo
    VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:  # pragma: no cover - depends on host tz database
    VN_TZ = _dt.timezone(_dt.timedelta(hours=7))


def now():
    """Current time as an aware datetime in Vietnam time."""
    return _dt.datetime.now(VN_TZ)


def today():
    """Today's date in Vietnam (not the host's date)."""
    return now().date()


def from_ts(ts):
    """Epoch seconds -> aware datetime in Vietnam time."""
    return _dt.datetime.fromtimestamp(ts, VN_TZ)


def to_ts(dt):
    """Vietnam wall-clock datetime -> epoch seconds.

    A naive datetime is read as Vietnam time (never host time)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=VN_TZ)
    return dt.timestamp()


def fmt(ts, pattern="%d/%m/%Y"):
    """Format an epoch in Vietnam time."""
    return from_ts(ts).strftime(pattern)
