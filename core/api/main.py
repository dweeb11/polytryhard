from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from core.api.middleware import request_id_middleware
from core.db.session import check_database
from core.settings import Settings, get_settings
from core.utils.time import now_iso


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(title="polytryhard", version=resolved.app_version)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in resolved.cors_allow_origins.split(",")],
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.middleware("http")(request_id_middleware)

    @app.get("/healthz")
    def healthz(request: Request, response: Response) -> dict[str, Any]:
        db_shared = check_database(resolved.database_url_shared)
        db_per_env = check_database(resolved.database_url_per_env)
        status = "degraded" if "down" in {db_shared, db_per_env} else "ok"
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
