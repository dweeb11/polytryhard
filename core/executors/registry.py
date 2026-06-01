from core.contracts.executor import Executor
from core.executors.paper.executor import PaperExecutor
from core.settings import Settings

_ALL_EXECUTORS: tuple[Executor, ...] = (PaperExecutor(),)


def registered_executors() -> tuple[Executor, ...]:
    return _ALL_EXECUTORS


def default_executor(settings: Settings) -> Executor:
    # M4.8+: select executor from settings (paper vs live stub).
    del settings
    return _ALL_EXECUTORS[0]
