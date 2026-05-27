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
    )
    assert settings.require_dbs is True
