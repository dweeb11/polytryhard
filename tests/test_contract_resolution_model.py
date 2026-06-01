from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db.shared_enums import ContractResolution
from core.db.shared_models import ContractResolutionRow, ReferenceMarketRow


def test_contract_resolution_round_trip(per_env_sqlite_urls: tuple[str, str]) -> None:
    shared_url, _ = per_env_sqlite_urls
    engine = create_engine(shared_url)
    with Session(engine) as session:
        session.add(
            ReferenceMarketRow(
                ticker="KXHIGHNY-25JUN01-T70",
                series="KXHIGHNY",
                title="NYC high temp",
                settlement_source=None,
                settlement_ref=None,
                open_time=None,
                close_time=None,
                settlement_time=None,
                status="closed",
                raw_jsonb={},
            )
        )
        session.flush()
        session.add(
            ContractResolutionRow(
                ticker="KXHIGHNY-25JUN01-T70",
                resolved_at=datetime(2026, 6, 2, tzinfo=UTC),
                resolution=ContractResolution.YES,
                settlement_value=Decimal("1"),
                source_evidence_jsonb={"result": "yes"},
            )
        )
        session.commit()

        row = session.scalar(select(ContractResolutionRow))
        assert row is not None
        assert row.ticker == "KXHIGHNY-25JUN01-T70"
        assert row.resolution == ContractResolution.YES
        assert row.settlement_value == Decimal("1")


def test_contract_resolution_rejects_orphan_without_reference_market(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    engine = create_engine(shared_url)
    with Session(engine) as session:
        session.add(
            ContractResolutionRow(
                ticker="KXHIGHNY-ORPHAN",
                resolved_at=datetime(2026, 6, 2, tzinfo=UTC),
                resolution=ContractResolution.NO,
                settlement_value=Decimal("0"),
                source_evidence_jsonb={"result": "no"},
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
