from datetime import UTC, datetime

from core.clock import FakeClock, WallClock


def test_wall_clock_returns_utc_aware_now() -> None:
    now = WallClock().now()
    assert now.tzinfo == UTC


def test_fake_clock_advances() -> None:
    start = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    clock = FakeClock(start=start)
    assert clock.now() == start
    clock.advance(30)
    assert clock.now() == datetime(2026, 5, 28, 12, 0, 30, tzinfo=UTC)
