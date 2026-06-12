from core.contracts.source import IngestionSource
from core.settings import Settings
from core.sources.kalshi import KalshiMarketsSource
from core.sources.kalshi.resolution import KalshiResolutionSource
from core.sources.open_meteo import OpenMeteoSource

_ALL_SOURCES: tuple[IngestionSource, ...] = (
    KalshiMarketsSource(),
    OpenMeteoSource(),
    KalshiResolutionSource(),
)


def registered_sources() -> tuple[IngestionSource, ...]:
    return _ALL_SOURCES


def enabled_sources(settings: Settings) -> list[IngestionSource]:
    return [source for source in _ALL_SOURCES if source.is_enabled(settings)]
