from datetime import UTC, datetime

from core.utils.time import now_iso


def test_now_iso_returns_utc_iso_timestamp() -> None:
    timestamp = now_iso()

    assert timestamp.endswith("Z")
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    assert parsed.tzinfo == UTC
