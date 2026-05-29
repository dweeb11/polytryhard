from core.contracts.source import IngestionSource
from core.settings import Settings

_ALL_SOURCES: tuple[IngestionSource, ...] = ()


def registered_sources() -> tuple[IngestionSource, ...]:
    return _ALL_SOURCES


def enabled_sources(settings: Settings) -> list[IngestionSource]:
    return [source for source in _ALL_SOURCES if source.is_enabled(settings)]
