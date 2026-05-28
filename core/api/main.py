from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from core.api.middleware import request_id_middleware
from core.api.v1.routes import router as v1_router
from core.db.session import check_database, per_env_session
from core.ledger.seed import seed_strategies_if_needed
from core.migrations import run_upgrade
from core.settings import Settings, get_settings
from core.utils.time import now_iso


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    if settings.database_url_per_env:
        run_upgrade("per_env", settings.database_url_per_env)
        with per_env_session(settings) as session:
            seed_strategies_if_needed(session, request_id="startup_seed")
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(title="polytryhard", version=resolved.app_version, lifespan=lifespan)
    app.state.settings = resolved

    def _settings_for_app() -> Settings:
        return resolved

    app.dependency_overrides[get_settings] = _settings_for_app
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in resolved.cors_allow_origins.split(",")],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.middleware("http")(request_id_middleware)
    app.include_router(v1_router)

    @app.get("/healthz")
    def healthz(request: Request, response: Response) -> dict[str, Any]:
        db_shared = check_database(resolved.database_url_shared)
        db_per_env = check_database(resolved.database_url_per_env)
        db_states = {db_shared, db_per_env}
        status = "degraded" if db_states & {"down", "unconfigured"} else "ok"
        if status == "degraded":
            response.status_code = 503
        return {
            "status": status,
            "version": resolved.app_version,
            "git_sha": resolved.git_sha,
            "request_id": request.state.request_id,
            "checked_at": now_iso(),
            "db_shared": db_shared,
            "db_per_env": db_per_env,
        }

    return app


app = create_app()
