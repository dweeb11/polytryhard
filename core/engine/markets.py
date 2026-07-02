from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from core.db.shared_enums import FeatureSubjectKind
from core.domain.feature import FeatureStatus, FeatureValue
from core.domain.market import MarketState
from core.domain.weather_markets import location_for_series
from core.features.queries import latest_market_snapshot, list_open_markets

logger = logging.getLogger(__name__)


def _market_series(market: object, ticker: str) -> str:
    series = getattr(market, "series", "")
    return str(series or ticker.split("-", 1)[0])


def build_market_states(session: Session, as_of: datetime) -> list[MarketState]:
    markets: list[MarketState] = []
    for market in list_open_markets(session, as_of=as_of):
        snapshot = latest_market_snapshot(session, ticker=market.ticker, as_of=as_of)
        if snapshot is None:
            continue
        series = _market_series(market, market.ticker)
        markets.append(
            MarketState(
                ticker=market.ticker,
                series=series,
                bid_yes=snapshot.bid_yes,
                ask_yes=snapshot.ask_yes,
                mid_yes=snapshot.mid_yes,
                as_of=snapshot.as_of,
                location_id=location_for_series(series),
            )
        )
    return markets


def index_features(features: list[FeatureValue]) -> dict[str, FeatureValue]:
    indexed: dict[str, FeatureValue] = {}
    for feature in features:
        key = f"{feature.provider_name}:{feature.subject_kind}:{feature.subject_id}"
        indexed[key] = feature
    return indexed


def _aggregate_location_parts(
    parts: list[FeatureValue],
    *,
    location_id: str,
) -> FeatureValue | None:
    """Unweighted arithmetic mean of a provider's per-model location parts."""
    numerics: list[Decimal] = []
    as_ofs: list[datetime] = []
    template: FeatureValue | None = None
    for part in parts:
        if (
            part.status == FeatureStatus.PRESENT
            and part.value_numeric is not None
            and part.as_of is not None
        ):
            if template is None:
                template = part
            numerics.append(part.value_numeric)
            as_ofs.append(part.as_of)
    if template is None:
        return None
    mean_val = sum(numerics, Decimal(0)) / Decimal(len(numerics))
    as_of = max(as_ofs)
    return FeatureValue.present(
        provider_name=template.provider_name,
        provider_version=template.provider_version,
        subject_kind=template.subject_kind,
        subject_id=location_id,
        as_of=as_of,
        value_numeric=mean_val,
    )


def strategy_features_for_market(
    indexed: dict[str, FeatureValue],
    *,
    location_id: str | None,
    ticker: str,
) -> dict[str, FeatureValue]:
    """Build the final feature dict passed to ``Strategy.evaluate()`` for one market.

    Keys are provider names (e.g. ``ensemble_mean_temp``). Market-subject features
    match the market ticker; location-subject features match the market's
    location. Per-model location parts (subject_id ``"<location>:<model>"``) are
    aggregated into a single location rollup when the provider did not already
    emit one. Unrecognized ``subject_kind`` values are dropped with a warning.
    Provider names are unique in the returned dict; the first matching row wins
    (stable index order). Strategies must consume this dict as-is — no per-strategy
    re-scoping.
    """
    by_name: dict[str, FeatureValue] = {}
    parts_by_provider: dict[str, list[FeatureValue]] = {}
    unknown_kinds: set[str] = set()
    for feature in indexed.values():
        if feature.subject_kind == FeatureSubjectKind.MARKET:
            if feature.subject_id == ticker:
                by_name.setdefault(feature.provider_name, feature)
        elif feature.subject_kind == FeatureSubjectKind.LOCATION:
            if location_id is None:
                continue
            if feature.subject_id == location_id:
                by_name.setdefault(feature.provider_name, feature)
            elif feature.subject_id.startswith(f"{location_id}:"):
                parts_by_provider.setdefault(feature.provider_name, []).append(feature)
        else:
            unknown_kinds.add(feature.subject_kind)
    if unknown_kinds:
        logger.warning(
            "strategy_features_for_market dropped unrecognized subject_kind(s): %s",
            sorted(unknown_kinds),
        )
    if location_id is not None:
        # NOTE(APP-206): unweighted mean until FeatureProvider.aggregate() exists.
        for provider_name, parts in parts_by_provider.items():
            if provider_name in by_name:
                continue
            aggregated = _aggregate_location_parts(parts, location_id=location_id)
            if aggregated is not None:
                by_name[provider_name] = aggregated
    return by_name


def features_snapshot(features: dict[str, FeatureValue]) -> dict[str, object]:
    return {name: feature.to_snapshot() for name, feature in features.items()}


def total_bankroll_cents(session: Session) -> int:
    from sqlalchemy import func, select

    from core.db.models import StrategyInstanceRow

    total = session.scalar(select(func.coalesce(func.sum(StrategyInstanceRow.bankroll_cents), 0)))
    return int(total or 0)
