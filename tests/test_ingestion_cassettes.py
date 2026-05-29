import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.db.shared_enums import ForecastSource
from core.sources.kalshi.parse import parse_market, parse_orderbook
from core.sources.open_meteo import parse_ensemble_response

CASSETTES = Path(__file__).resolve().parent / "cassettes"


def test_parse_kalshi_market_cassette() -> None:
    payload = json.loads((CASSETTES / "kalshi_markets_discovery.json").read_text())
    market = parse_market(payload["markets"][0])
    assert market is not None
    assert market.ticker == "KXHIGHNY-25MAY28-T72"
    assert market.series == "KXHIGHNY"
    assert market.status == "open"


def test_parse_kalshi_orderbook_cassette() -> None:
    payload = json.loads((CASSETTES / "kalshi_orderbook.json").read_text())
    as_of = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    snapshot = parse_orderbook(ticker="KXHIGHNY-25MAY28-T72", as_of=as_of, payload=payload)
    assert snapshot is not None
    assert snapshot.bid_yes is not None
    assert snapshot.ask_yes is not None
    assert snapshot.last_trade_price is None


def test_parse_open_meteo_ensemble_cassette() -> None:
    payload = json.loads((CASSETTES / "open_meteo_ensemble.json").read_text())
    ingested_at = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    rows = parse_ensemble_response(
        payload=payload,
        source=ForecastSource.GFS,
        location_id="houston",
        ingested_at=ingested_at,
        timezone="America/Chicago",
    )
    assert len(rows) == 4
    assert rows[0].location_id == "houston"
    assert rows[0].variable == "temperature_2m"
    assert rows[0].ensemble_member == 0
    assert rows[2].ensemble_member == 1
    assert rows[0].valid_window_end == rows[0].valid_window_start + timedelta(hours=1)


def test_parse_open_meteo_ensemble_cassette_timezone() -> None:
    payload = json.loads((CASSETTES / "open_meteo_ensemble.json").read_text())
    ingested_at = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    rows = parse_ensemble_response(
        payload=payload,
        source=ForecastSource.GFS,
        location_id="houston",
        ingested_at=ingested_at,
        timezone="America/Chicago",
    )
    # Cassette time 2026-05-28T12:00 is local CDT (UTC-5) → 17:00 UTC
    assert rows[0].valid_window_start == datetime(2026, 5, 28, 17, 0, tzinfo=UTC)


def test_parse_open_meteo_ensemble_cassette_ecmwf_source() -> None:
    payload = json.loads((CASSETTES / "open_meteo_ensemble.json").read_text())
    ingested_at = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    rows = parse_ensemble_response(
        payload=payload,
        source=ForecastSource.ECMWF,
        location_id="houston",
        ingested_at=ingested_at,
        timezone="America/Chicago",
    )
    assert len(rows) == 4
    assert rows[0].source == ForecastSource.ECMWF
