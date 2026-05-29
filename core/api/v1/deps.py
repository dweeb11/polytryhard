import hmac
from collections.abc import Generator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from core.db.session import per_env_session
from core.settings import Settings, get_settings


def get_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", "")
    if not isinstance(request_id, str):
        raise RuntimeError("request_id missing from request state")
    return request_id


def verify_bearer_token(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.control_plane_token is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="unconfigured")
    header = request.headers.get("authorization", "")
    prefix = "Bearer "
    if not header.startswith(prefix):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    token = header[len(prefix) :]
    if not hmac.compare_digest(token, settings.control_plane_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


def per_env_db(
    settings: Settings = Depends(get_settings),
) -> Generator[Session, None, None]:
    with per_env_session(settings) as session:
        yield session
