from core.contracts.feature import FeatureProvider
from core.features.ensemble_mean_temp import EnsembleMeanTempProvider
from core.features.forecast_disagreement import ForecastDisagreementProvider
from core.features.kalshi_spread import KalshiSpreadProvider
from core.features.weather_model_prob import WeatherModelProbProvider
from core.settings import Settings

_ALL_PROVIDERS: tuple[FeatureProvider, ...] = (
    EnsembleMeanTempProvider(),
    ForecastDisagreementProvider(),
    KalshiSpreadProvider(),
    WeatherModelProbProvider(),
)


def registered_feature_providers() -> tuple[FeatureProvider, ...]:
    return _ALL_PROVIDERS


def enabled_feature_providers(settings: Settings) -> list[FeatureProvider]:
    return [provider for provider in _ALL_PROVIDERS if provider.is_enabled(settings)]
