"""Curated reference_location rows for Open-Meteo ingestion.

Insert-if-missing on startup (same pattern as core/ledger/seed.py). Existing rows
are never updated — coordinate or station changes require a migration or manual fix.

Concurrent startup (multiple API workers) can race on the same primary key and raise
IntegrityError on insert; Coolify runs a single process today. Use one worker or add
ON CONFLICT DO NOTHING if multi-worker deploy is required.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from core.db.shared_models import ReferenceLocationRow

LocationSeed = tuple[str, str, str, Decimal, Decimal, str, str]

# Airport station codes (ICAO) for Open-Meteo lat/lon queries. Kalshi settlement
# may reference different NWS stations later; update via migration if that diverges.
SEED_LOCATIONS: tuple[LocationSeed, ...] = (
    (
        "houston",
        "KIAH",
        "Houston",
        Decimal("29.9844"),
        Decimal("-95.3414"),
        "America/Chicago",
        "curated",
    ),
    (
        "nyc",
        "KJFK",
        "New York City",
        Decimal("40.6413"),
        Decimal("-73.7781"),
        "America/New_York",
        "curated",
    ),
    (
        "chicago",
        "KORD",
        "Chicago",
        Decimal("41.9742"),
        Decimal("-87.9073"),
        "America/Chicago",
        "curated",
    ),
    (
        "austin",
        "KAUS",
        "Austin",
        Decimal("30.1975"),
        Decimal("-97.6664"),
        "America/Chicago",
        "curated",
    ),
    (
        "miami",
        "KMIA",
        "Miami",
        Decimal("25.7959"),
        Decimal("-80.2870"),
        "America/New_York",
        "curated",
    ),
    (
        "la",
        "KLAX",
        "Los Angeles",
        Decimal("33.9425"),
        Decimal("-118.4081"),
        "America/Los_Angeles",
        "curated",
    ),
)


def seed_locations_if_needed(session: Session) -> None:
    for location_id, station_code, name, lat, lon, timezone, source in SEED_LOCATIONS:
        existing = session.get(ReferenceLocationRow, location_id)
        if existing is not None:
            continue
        session.add(
            ReferenceLocationRow(
                id=location_id,
                station_code=station_code,
                name=name,
                lat=lat,
                lon=lon,
                timezone=timezone,
                source=source,
            )
        )
    session.commit()
