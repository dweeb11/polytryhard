from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from core.contracts.feature import FeatureContext, FeatureProvider
from core.db.shared_enums import FeatureSubjectKind
from core.domain.feature import FeatureValue
from core.features.queries import latest_market_snapshot, list_open_markets
from core.settings import Settings


class KalshiSpreadProvider(FeatureProvider):
    @property
    def name(self) -> str:
        return "kalshi_spread"

    @property
    def version(self) -> str:
        return "1"

    def is_enabled(self, settings: Settings) -> bool:
        return True

    async def compute(self, as_of: datetime, ctx: FeatureContext) -> list[FeatureValue]:
        results: list[FeatureValue] = []
        subject_kind = FeatureSubjectKind.MARKET.value
        for market in list_open_markets(ctx.session, as_of=as_of):
            snapshot = latest_market_snapshot(ctx.session, ticker=market.ticker, as_of=as_of)
            if snapshot is None:
                results.append(
                    FeatureValue.missing(
                        provider_name=self.name,
                        provider_version=self.version,
                        subject_kind=subject_kind,
                        subject_id=market.ticker,
                        reason="no market snapshot",
                    )
                )
                continue
            if snapshot.bid_yes is None or snapshot.ask_yes is None:
                results.append(
                    FeatureValue.missing(
                        provider_name=self.name,
                        provider_version=self.version,
                        subject_kind=subject_kind,
                        subject_id=market.ticker,
                        reason="incomplete quote",
                    )
                )
                continue
            spread = snapshot.ask_yes - snapshot.bid_yes
            if spread < Decimal("0"):
                results.append(
                    FeatureValue.missing(
                        provider_name=self.name,
                        provider_version=self.version,
                        subject_kind=subject_kind,
                        subject_id=market.ticker,
                        reason="invalid spread",
                    )
                )
                continue
            results.append(
                FeatureValue.present(
                    provider_name=self.name,
                    provider_version=self.version,
                    subject_kind=subject_kind,
                    subject_id=market.ticker,
                    as_of=snapshot.as_of,
                    value_numeric=spread,
                    value_jsonb={
                        "bidYes": float(snapshot.bid_yes),
                        "askYes": float(snapshot.ask_yes),
                        "midYes": float(snapshot.mid_yes) if snapshot.mid_yes is not None else None,
                    },
                )
            )
        return results
