import os
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _require_dbs_enabled() -> bool:
    return os.environ.get("REQUIRE_DBS", "1").strip().lower() in ("1", "true", "yes")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    git_sha: str = Field(default="dev", alias="GIT_SHA")
    database_url_shared: str | None = Field(default=None, alias="DATABASE_URL_SHARED")
    database_url_per_env: str | None = Field(default=None, alias="DATABASE_URL_PER_ENV")
    cors_allow_origins: str = Field(default="*", alias="CORS_ALLOW_ORIGINS")

    @model_validator(mode="after")
    def require_database_urls_when_enforced(self) -> "Settings":
        if not _require_dbs_enabled():
            return self
        missing: list[str] = []
        if self.database_url_shared is None:
            missing.append("DATABASE_URL_SHARED")
        if self.database_url_per_env is None:
            missing.append("DATABASE_URL_PER_ENV")
        if missing:
            raise ValueError(
                "Database URLs required when REQUIRE_DBS is enabled: " + ", ".join(missing)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
