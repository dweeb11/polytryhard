from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _empty_to_none(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    git_sha: str = Field(default="dev", alias="GIT_SHA")
    database_url_shared: str | None = Field(default=None, alias="DATABASE_URL_SHARED")
    database_url_per_env: str | None = Field(default=None, alias="DATABASE_URL_PER_ENV")
    cors_allow_origins: str = Field(default="*", alias="CORS_ALLOW_ORIGINS")
    require_dbs: bool = Field(default=True, alias="REQUIRE_DBS")
    control_plane_token: str | None = Field(default=None, alias="CONTROL_PLANE_TOKEN")
    scheduler_enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")
    source_failure_threshold: int = Field(default=3, alias="SOURCE_FAILURE_THRESHOLD")
    kalshi_api_key_id: str | None = Field(default=None, alias="KALSHI_API_KEY_ID")
    kalshi_private_key: str | None = Field(default=None, alias="KALSHI_PRIVATE_KEY")
    kalshi_api_base: str | None = Field(
        default="https://demo-api.kalshi.co",
        alias="KALSHI_API_BASE",
    )
    kalshi_series_prefixes_raw: str = Field(
        default="KXHIGH,KXLOW",
        alias="KALSHI_SERIES_PREFIXES",
    )

    @field_validator("control_plane_token", mode="before")
    @classmethod
    def normalize_control_plane_token(cls, value: Any) -> Any:
        return _empty_to_none(value)

    @field_validator(
        "database_url_shared",
        "database_url_per_env",
        "kalshi_api_key_id",
        "kalshi_private_key",
        mode="before",
    )
    @classmethod
    def normalize_database_url(cls, value: Any) -> Any:
        return _empty_to_none(value)


    @property
    def kalshi_configured(self) -> bool:
        return self.kalshi_api_key_id is not None and self.kalshi_private_key is not None

    @property
    def kalshi_series_prefixes(self) -> tuple[str, ...]:
        return tuple(
            part.strip()
            for part in self.kalshi_series_prefixes_raw.split(",")
            if part.strip()
        )

    @model_validator(mode="after")
    def require_database_urls_when_enforced(self) -> "Settings":
        if not self.require_dbs:
            return self
        missing: list[str] = []
        if self.database_url_shared is None:
            missing.append("DATABASE_URL_SHARED")
        if self.database_url_per_env is None:
            missing.append("DATABASE_URL_PER_ENV")
        if self.control_plane_token is None:
            missing.append("CONTROL_PLANE_TOKEN")
        if missing:
            raise ValueError(
                "Database URLs required when REQUIRE_DBS is enabled: " + ", ".join(missing)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
