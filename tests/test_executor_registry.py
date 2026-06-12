from core.executors.paper.executor import PaperExecutor
from core.executors.registry import default_executor, registered_executors
from core.settings import Settings


def test_registered_executors_includes_paper() -> None:
    executors = registered_executors()
    assert len(executors) == 1
    assert isinstance(executors[0], PaperExecutor)


def test_default_executor_returns_paper() -> None:
    settings = Settings(
        REQUIRE_DBS=False,
        DATABASE_URL_SHARED="sqlite:///:memory:",
        DATABASE_URL_PER_ENV="sqlite:///:memory:",
    )
    assert isinstance(default_executor(settings), PaperExecutor)
