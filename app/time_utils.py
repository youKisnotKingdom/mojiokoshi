from datetime import datetime, timedelta, timezone

TOKYO_TZ = timezone(timedelta(hours=9), name="JST")


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def tokyo_now() -> datetime:
    """Return the current time in Asia/Tokyo."""
    return datetime.now(TOKYO_TZ)


def to_tokyo(dt: datetime | None) -> datetime | None:
    """Convert a datetime to Asia/Tokyo for display.

    Naive datetimes are treated as UTC because DB-backed timestamps are stored
    in UTC or returned without tzinfo depending on the driver configuration.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TOKYO_TZ)
