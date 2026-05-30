from enum import StrEnum


class ForecastSource(StrEnum):
    GFS = "gfs"
    ECMWF = "ecmwf"


class SourceRunStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    ERROR = "error"


class FeatureSubjectKind(StrEnum):
    """M4.1 scope: market and location. PDD also lists article — deferred to news features."""

    MARKET = "market"
    LOCATION = "location"
