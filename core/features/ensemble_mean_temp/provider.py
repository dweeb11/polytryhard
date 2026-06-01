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


class EnsembleMeanTempProvider(FeatureProvider):
    @property
    def name(self) -> str:
        return "ensemble_mean_temp"

    @property
    def version(self) -> str:
        return "1"

    def is_enabled(self, settings: Settings) -> bool:
        return True

    async def compute(self, as_of: datetime, ctx: FeatureContext) -> list[FeatureValue]:
        results: list[FeatureValue] = []
        subject_kind = FeatureSubjectKind.LOCATION.value
        for location in list_locations(ctx.session):
            for source in (ForecastSource.GFS, ForecastSource.ECMWF):
                subject_id = f"{location.id}:{source.value}"
                rows = latest_forecast_rows(
                    ctx.session,
                    location_id=location.id,
                    source=source,
                    variable=TEMPERATURE_VARIABLE,
                    as_of=as_of,
                    target_window_start=ctx.target_window_start,
                )
                if not rows:
                    results.append(
                        FeatureValue.missing(
                            provider_name=self.name,
                            provider_version=self.version,
                            subject_kind=subject_kind,
                            subject_id=subject_id,
                            reason="no forecast rows",
                        )
                    )
                    continue
                mean = ensemble_mean(rows)
                if mean is None:
                    results.append(
                        FeatureValue.missing(
                            provider_name=self.name,
                            provider_version=self.version,
                            subject_kind=subject_kind,
                            subject_id=subject_id,
                            reason="empty ensemble",
                        )
                    )
                    continue
                as_of_value = latest_forecast_as_of(rows)
                if as_of_value is None:
                    results.append(
                        FeatureValue.missing(
                            provider_name=self.name,
                            provider_version=self.version,
                            subject_kind=subject_kind,
                            subject_id=subject_id,
                            reason="empty ensemble",
                        )
                    )
                    continue
                results.append(
                    FeatureValue.present(
                        provider_name=self.name,
                        provider_version=self.version,
                        subject_kind=subject_kind,
                        subject_id=subject_id,
                        as_of=as_of_value,
                        value_numeric=mean,
                        value_jsonb={"source": source.value},
                    )
                )
        return results
