from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from core.settings import Settings, get_settings


_MAX_ENGINE_CACHE = 8
_engines: OrderedDict[str, Engine] = OrderedDict()


def make_engine(database_url: str) -> Engine:
    cached = _engines.get(database_url)
    if cached is not None:
        _engines.move_to_end(database_url)
        return cached
    engine = create_engine(database_url, pool_pre_ping=True)
    _engines[database_url] = engine
    while len(_engines) > _MAX_ENGINE_CACHE:
        _, evicted = _engines.popitem(last=False)
        evicted.dispose()
    return engine


def _session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=make_engine(database_url), expire_on_commit=False)


@contextmanager
def shared_session(settings: Settings | None = None) -> Iterator[Session]:
    resolved = settings or get_settings()
    if resolved.database_url_shared is None:
        raise RuntimeError("DATABASE_URL_SHARED is not configured")
    with _session_factory(resolved.database_url_shared)() as session:
        yield session


@contextmanager
def per_env_session(settings: Settings | None = None) -> Iterator[Session]:
    resolved = settings or get_settings()
    if resolved.database_url_per_env is None:
        raise RuntimeError("DATABASE_URL_PER_ENV is not configured")
    with _session_factory(resolved.database_url_per_env)() as session:
        yield session


def check_database(database_url: str | None) -> str:
    if database_url is None or not database_url.strip():
        return "unconfigured"
    try:
        with make_engine(database_url).connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return "down"
    return "ok"
