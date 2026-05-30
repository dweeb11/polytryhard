from core.contracts.feature import FeatureProvider
from core.settings import Settings

_ALL_PROVIDERS: tuple[FeatureProvider, ...] = ()


def registered_feature_providers() -> tuple[FeatureProvider, ...]:
    return _ALL_PROVIDERS


def enabled_feature_providers(settings: Settings) -> list[FeatureProvider]:
    return [provider for provider in _ALL_PROVIDERS if provider.is_enabled(settings)]
