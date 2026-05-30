from __future__ import annotations

from datetime import datetime

from core.contracts.feature import FeatureContext, FeatureProvider
from core.db.shared_enums import FeatureSubjectKind, ForecastSource
from core.domain.feature import FeatureValue
from core.features.queries import (
    TEMPERATURE_VARIABLE,
    ensemble_mean,
    latest_forecast_as_of,
    latest_forecast_rows,
    list_locations,
)
from core.settings import Settings


class ForecastDisagreementProvider(FeatureProvider):
    @property
    def name(self) -> str:
        return "forecast_disagreement"

    @property
    def version(self) -> str:
        return "1"

    def is_enabled(self, settings: Settings) -> bool:
        return True

    async def compute(self, as_of: datetime, ctx: FeatureContext) -> list[FeatureValue]:
        results: list[FeatureValue] = []
        subject_kind = FeatureSubjectKind.LOCATION.value
        for location in list_locations(ctx.session):
            gfs_rows = latest_forecast_rows(
                ctx.session,
                location_id=location.id,
                source=ForecastSource.GFS,
                variable=TEMPERATURE_VARIABLE,
                as_of=as_of,
            )
            ecmwf_rows = latest_forecast_rows(
                ctx.session,
                location_id=location.id,
                source=ForecastSource.ECMWF,
                variable=TEMPERATURE_VARIABLE,
                as_of=as_of,
            )
            if not gfs_rows or not ecmwf_rows:
                results.append(
                    FeatureValue.missing(
                        provider_name=self.name,
                        provider_version=self.version,
                        subject_kind=subject_kind,
                        subject_id=location.id,
                        reason="missing model forecast",
                    )
                )
                continue
            gfs_mean = ensemble_mean(gfs_rows)
            ecmwf_mean = ensemble_mean(ecmwf_rows)
            if gfs_mean is None or ecmwf_mean is None:
                results.append(
                    FeatureValue.missing(
                        provider_name=self.name,
                        provider_version=self.version,
                        subject_kind=subject_kind,
                        subject_id=location.id,
                        reason="empty ensemble",
                    )
                )
                continue
            disagreement = abs(gfs_mean - ecmwf_mean)
            as_of_value = max(
                latest_forecast_as_of(gfs_rows) or as_of,
                latest_forecast_as_of(ecmwf_rows) or as_of,
            )
            results.append(
                FeatureValue.present(
                    provider_name=self.name,
                    provider_version=self.version,
                    subject_kind=subject_kind,
                    subject_id=location.id,
                    as_of=as_of_value,
                    value_numeric=disagreement,
                    value_jsonb={
                        "gfsMean": float(gfs_mean),
                        "ecmwfMean": float(ecmwf_mean),
                    },
                )
            )
        return results
