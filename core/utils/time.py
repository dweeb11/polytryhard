from datetime import UTC, datetime


def now_iso() -> str:
    """Return an as-of-safe UTC timestamp for persisted backend events."""
    return datetime.now(tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
