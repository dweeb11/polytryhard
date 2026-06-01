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
    resolutions = shared_session.scalars(select(ContractResolutionRow)).all()
    resolved = 0
    for res in resolutions:
        open_positions = per_env_session.scalars(
            select(PaperPositionRow).where(
                PaperPositionRow.ticker == res.ticker,
                PaperPositionRow.status == DbPositionStatus.OPEN,
            )
        ).all()
        for position in open_positions:
            writer.resolve_position(
                per_env_session,
                position=position,
                resolution=ContractResolution(res.resolution),
                settlement_value=res.settlement_value,
                actor=AuditActor.SCHEDULER,
                request_id=tick_id,
            )
            resolved += 1
    per_env_session.commit()
    logger.info("resolution tick complete request_id=%s resolved=%s", tick_id, resolved)
    return {"resolved": resolved}
