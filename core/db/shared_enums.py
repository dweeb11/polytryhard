from enum import StrEnum


class ForecastSource(StrEnum):
    GFS = "gfs"
    ECMWF = "ecmwf"


class SourceRunStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    ERROR = "error"


class FeatureSubjectKind(StrEnum):
    MARKET = "market"
    LOCATION = "location"
