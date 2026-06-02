from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.enums import PositionStatus as DbPositionStatus
from core.db.models import PaperPositionRow
from core.db.shared_enums import ContractResolution
from core.db.shared_models import ContractResolutionRow
from core.domain.enums import AuditActor
from core.ledger import writer
from core.utils.time import utc_now

logger = logging.getLogger(__name__)


def _resolution_request_id() -> str:
    return f"resolution_{uuid4().hex[:12]}"


def run_resolution_tick(
    *,
    shared_session: Session,
    per_env_session: Session,
    request_id: str | None = None,
) -> dict[str, int]:
    tick_id = request_id or _resolution_request_id()
    open_positions = per_env_session.scalars(
        select(PaperPositionRow).where(PaperPositionRow.status == DbPositionStatus.OPEN)
    ).all()
    resolved = 0
    if open_positions:
        tickers = {position.ticker for position in open_positions}
        resolutions_by_ticker = {
            row.ticker: row
            for row in shared_session.scalars(
                select(ContractResolutionRow).where(ContractResolutionRow.ticker.in_(tickers))
            ).all()
        }
        affected: set[str] = set()
        for position in open_positions:
            res = resolutions_by_ticker.get(position.ticker)
            if res is None:
                continue
            writer.resolve_position(
                per_env_session,
                position=position,
                resolution=ContractResolution(res.resolution),
                settlement_value=res.settlement_value,
                actor=AuditActor.SCHEDULER,
                request_id=tick_id,
            )
            affected.add(position.strategy_name)
            resolved += 1
        if affected:
            from core.eval.snapshot import recompute_strategy

            now = utc_now()
            for strategy_name in sorted(affected):
                recompute_strategy(
                    per_env_session=per_env_session,
                    shared_session=shared_session,
                    strategy_name=strategy_name,
                    now=now,
                )
    per_env_session.commit()
    logger.info("resolution tick complete request_id=%s resolved=%s", tick_id, resolved)
    return {"resolved": resolved}
