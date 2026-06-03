import pytest

from core.settings import Settings


def test_settings_raises_when_require_dbs_enabled_and_urls_missing() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL_SHARED"):
        Settings(
            REQUIRE_DBS=True,
            DATABASE_URL_SHARED=None,
            DATABASE_URL_PER_ENV=None,
        )


def test_settings_allows_missing_urls_when_require_dbs_disabled() -> None:
    settings = Settings(
        REQUIRE_DBS=False,
        DATABASE_URL_SHARED=None,
        DATABASE_URL_PER_ENV=None,
    )
    assert settings.require_dbs is False
    assert settings.database_url_shared is None
    assert settings.database_url_per_env is None


def test_settings_rejects_blank_database_urls_when_require_dbs_enabled() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL_SHARED"):
        Settings(
            REQUIRE_DBS=True,
            DATABASE_URL_SHARED="   ",
            DATABASE_URL_PER_ENV="postgresql+psycopg://localhost/per_env",
        )


def test_require_dbs_parses_string_zero() -> None:
    settings = Settings(REQUIRE_DBS="0")
    assert settings.require_dbs is False


def test_require_dbs_parses_common_truthy_env_values() -> None:
    settings = Settings(
        REQUIRE_DBS="on",
        DATABASE_URL_SHARED="postgresql+psycopg://localhost/shared",
        DATABASE_URL_PER_ENV="postgresql+psycopg://localhost/per_env",
        CONTROL_PLANE_TOKEN="secret",
    )
    assert settings.require_dbs is True


def test_kalshi_api_base_strips_trade_api_suffix() -> None:
    settings = Settings(
        REQUIRE_DBS=False,
        KALSHI_API_BASE="https://external-api.demo.kalshi.co/trade-api/v2",
    )
    assert settings.kalshi_api_base_url == "https://external-api.demo.kalshi.co"


def test_settings_raises_when_control_plane_token_missing() -> None:
    with pytest.raises(ValueError, match="CONTROL_PLANE_TOKEN"):
        Settings(
            REQUIRE_DBS=True,
            DATABASE_URL_SHARED="postgresql+psycopg://localhost/shared",
            DATABASE_URL_PER_ENV="postgresql+psycopg://localhost/per_env",
            CONTROL_PLANE_TOKEN=None,
        )


def test_paper_strategy_bankroll_overrides_parse_json() -> None:
    settings = Settings(
        REQUIRE_DBS=False,
        PAPER_STRATEGY_BANKROLL_CENTS_JSON='{"weather_stale_quote":15000}',
    )
    assert settings.paper_strategy_bankroll_cents == {"weather_stale_quote": 15_000}


def test_paper_initial_bankroll_must_be_positive() -> None:
    with pytest.raises(ValueError, match="PAPER_INITIAL_BANKROLL_CENTS"):
        Settings(REQUIRE_DBS=False, PAPER_INITIAL_BANKROLL_CENTS=0)


def test_paper_strategy_bankroll_overrides_must_be_positive() -> None:
    with pytest.raises(ValueError, match="PAPER_STRATEGY_BANKROLL_CENTS_JSON"):
        Settings(
            REQUIRE_DBS=False,
            PAPER_STRATEGY_BANKROLL_CENTS_JSON={"weather_stale_quote": 0},
        )
