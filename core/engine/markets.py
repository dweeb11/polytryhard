from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from core.domain.feature import FeatureValue
from core.domain.market import MarketState
from core.features.queries import latest_market_snapshot, list_open_markets
from core.strategies.weather_utils import location_for_series


def build_market_states(session: Session, as_of: datetime) -> list[MarketState]:
    markets: list[MarketState] = []
    for market in list_open_markets(session):
        snapshot = latest_market_snapshot(session, ticker=market.ticker, as_of=as_of)
        if snapshot is None:
            continue
        markets.append(
            MarketState(
                ticker=market.ticker,
                series=market.series,
                bid_yes=snapshot.bid_yes,
                ask_yes=snapshot.ask_yes,
                mid_yes=snapshot.mid_yes,
                as_of=snapshot.as_of,
                location_id=location_for_series(market.series),
            )
        )
    return markets


def index_features(features: list[FeatureValue]) -> dict[str, FeatureValue]:
    indexed: dict[str, FeatureValue] = {}
    for feature in features:
        key = f"{feature.provider_name}:{feature.subject_kind}:{feature.subject_id}"
        indexed[key] = feature
    return indexed


def features_for_market(
    indexed: dict[str, FeatureValue],
    *,
    location_id: str | None,
    ticker: str,
) -> dict[str, FeatureValue]:
    by_name: dict[str, FeatureValue] = {}
    for feature in indexed.values():
        if feature.provider_name == "kalshi_spread" and feature.subject_id == ticker:
            by_name[feature.provider_name] = feature
        elif (
            location_id
            and feature.subject_id == location_id
            and feature.provider_name != "kalshi_spread"
        ):
            by_name[feature.provider_name] = feature
    return by_name


def features_snapshot(features: dict[str, FeatureValue]) -> dict[str, object]:
    return {name: feature.to_snapshot() for name, feature in features.items()}


def total_bankroll_cents(session: Session) -> int:
    from sqlalchemy import func, select

    from core.db.models import StrategyInstanceRow

    total = session.scalar(select(func.coalesce(func.sum(StrategyInstanceRow.bankroll_cents), 0)))
    return int(total or 0)
