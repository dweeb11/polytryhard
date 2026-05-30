from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from core.domain.feature import FeatureValue
from core.domain.market import MarketState, SignalDraft
from core.settings import Settings


@dataclass(frozen=True)
class StrategyContext:
    strategy_name: str
    config_jsonb: dict[str, object]
    tolerate_missing_features: bool = False


class Strategy(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def required_features(self) -> frozenset[str]:
        raise NotImplementedError

    @abstractmethod
    def is_enabled(self, settings: Settings) -> bool:
        raise NotImplementedError

    @abstractmethod
    def evaluate(
        self,
        market: MarketState,
        features: dict[str, FeatureValue],
        ctx: StrategyContext,
    ) -> SignalDraft | None:
        raise NotImplementedError


def required_features_present(
    required: frozenset[str],
    values: dict[str, FeatureValue],
    *,
    tolerate_missing: bool,
) -> bool:
    for name in required:
        feature = values.get(name)
        if feature is None or feature.status.value == "missing":
            if not tolerate_missing:
                return False
        elif feature.status.value != "present":
            if not tolerate_missing:
                return False
    return True
