from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return naive UTC for the existing SQLite DateTime columns."""
    return datetime.now(UTC).replace(tzinfo=None)


def utc_from_unix(value: int | float) -> datetime:
    """Convert a VK/Unix timestamp to naive UTC, never to the host timezone."""
    return datetime.fromtimestamp(float(value), UTC).replace(tzinfo=None)


def api_timestamp(value: datetime | None) -> str | None:
    """Serialize DB timestamps with an explicit UTC offset for browser-local display."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat()
