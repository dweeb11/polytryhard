from decimal import Decimal

from sqlalchemy import func, select

from core.db.session import shared_session
from core.db.shared_models import ReferenceLocationRow
from core.settings import Settings
from core.sources.seed import SEED_LOCATIONS, seed_locations_if_needed


def test_seed_locations_is_idempotent(per_env_sqlite_urls: tuple[str, str]) -> None:
    shared_url, _ = per_env_sqlite_urls
    settings = Settings(
        REQUIRE_DBS=False,
        DATABASE_URL_SHARED=shared_url,
        SCHEDULER_ENABLED=False,
    )
    with shared_session(settings) as session:
        seed_locations_if_needed(session)
        first_count = session.scalar(select(func.count()).select_from(ReferenceLocationRow))
        seed_locations_if_needed(session)
        second_count = session.scalar(select(func.count()).select_from(ReferenceLocationRow))

        houston = session.get(ReferenceLocationRow, "houston")
        assert houston is not None
        assert houston.station_code == "KIAH"
        assert houston.name == "Houston"
        assert houston.lat == Decimal("29.9844")
        assert houston.lon == Decimal("-95.3414")
        assert houston.timezone == "America/Chicago"
        assert houston.source == "curated"

        seeded_ids = {row.id for row in session.scalars(select(ReferenceLocationRow)).all()}
        assert seeded_ids == {loc[0] for loc in SEED_LOCATIONS}

    assert first_count == len(SEED_LOCATIONS)
    assert second_count == len(SEED_LOCATIONS)
