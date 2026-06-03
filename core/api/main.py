from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.api.middleware import request_id_middleware
from core.api.v1.routes import router as v1_router
from core.db.session import check_database, per_env_session, shared_session
from core.ledger.seed import seed_strategies_if_needed
from core.migrations import run_upgrade
from core.scheduler import Scheduler
from core.settings import Settings, get_settings
from core.sources.seed import seed_locations_if_needed
from core.utils.time import now_iso


class SchedulerCycleHealth(BaseModel):
    status: Literal["pending", "ok", "error"]
    last_error: str | None = None
    last_cycle_at: str | None = None
    last_success_at: str | None = None


class HealthzResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    git_sha: str
    request_id: str
    checked_at: str
    db_shared: str
    db_per_env: str
    scheduler_cycle: SchedulerCycleHealth | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    if settings.database_url_shared:
        run_upgrade("shared", settings.database_url_shared)
        with shared_session(settings) as session:
            seed_locations_if_needed(session)
    if settings.database_url_per_env:
        run_upgrade("per_env", settings.database_url_per_env)
        with per_env_session(settings) as session:
            seed_strategies_if_needed(session, request_id="startup_seed", settings=settings)
    if settings.database_url_shared and settings.scheduler_enabled:
        scheduler = Scheduler.create(settings)
        app.state.scheduler = scheduler
        await scheduler.start()
    try:
        yield
    finally:
        active = getattr(app.state, "scheduler", None)
        if isinstance(active, Scheduler):
            await active.stop()


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

    @app.get(
        "/healthz",
        response_model=HealthzResponse,
        responses={503: {"model": HealthzResponse}},
    )
    def healthz(request: Request, response: Response) -> dict[str, Any]:
        db_shared = check_database(resolved.database_url_shared)
        db_per_env = check_database(resolved.database_url_per_env)
        db_states = {db_shared, db_per_env}
        status = "degraded" if db_states & {"down", "unconfigured"} else "ok"
        payload: dict[str, Any] = {
            "status": status,
            "version": resolved.app_version,
            "git_sha": resolved.git_sha,
            "request_id": request.state.request_id,
            "checked_at": now_iso(),
            "db_shared": db_shared,
            "db_per_env": db_per_env,
        }
        scheduler = getattr(request.app.state, "scheduler", None)
        if isinstance(scheduler, Scheduler):
            cycle = scheduler.cycle_health
            cycle_status = cycle.status
            if cycle_status == "error" or (
                cycle_status == "pending" and resolved.scheduler_enabled
            ):
                payload["status"] = "degraded"
            payload["scheduler_cycle"] = {
                "status": cycle_status,
                "last_error": "scheduler cycle failed" if cycle.last_cycle_error else None,
                "last_cycle_at": (
                    cycle.last_cycle_at.isoformat() if cycle.last_cycle_at is not None else None
                ),
                "last_success_at": (
                    cycle.last_cycle_success_at.isoformat()
                    if cycle.last_cycle_success_at is not None
                    else None
                ),
            }
        if payload["status"] == "degraded":
            response.status_code = 503
        return payload

    return app


app = create_app()
