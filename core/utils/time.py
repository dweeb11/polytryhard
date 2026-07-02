from datetime import UTC, datetime


def now_iso() -> str:
    """Return an as-of-safe UTC timestamp for persisted backend events."""
    return to_iso(datetime.now(tz=UTC))


def to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def as_utc(value: datetime) -> datetime:
    """Normalize a datetime to UTC; naive values are assumed UTC (DB round-trip convention)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def format_dt(value: datetime) -> str:
    return to_iso(value)


def parse_iso(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
