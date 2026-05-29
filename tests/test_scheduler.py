from datetime import UTC, datetime

from core.db.shared_enums import SourceRunStatus
from core.sources.persistence import SourceHealthTracker


def test_health_tracker_marks_degraded_after_threshold() -> None:
    tracker = SourceHealthTracker(failure_threshold=2)
    finished = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    tracker.record_failure("open_meteo", finished_at=finished, error="boom")
    assert tracker.get("open_meteo").status == SourceRunStatus.ERROR
    tracker.record_failure("open_meteo", finished_at=finished, error="boom")
    assert tracker.get("open_meteo").status == SourceRunStatus.DEGRADED
