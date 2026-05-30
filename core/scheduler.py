from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from uuid import uuid4

import httpx

from core.clock import Clock, WallClock
from core.contracts.source import FetchResult, IngestionSource, SourceContext
from core.db.session import per_env_session, shared_session
from core.db.shared_enums import SourceRunStatus
from core.settings import Settings
from core.sources.persistence import (
    SourceHealthSnapshot,
    SourceHealthTracker,
    load_locations,
    load_markets,
    persist_fetch_result,
)
from core.sources.registry import enabled_sources, registered_sources

logger = logging.getLogger(__name__)


def _tick_request_id(source_name: str) -> str:
    return f"tick_{source_name}_{uuid4().hex[:12]}"


class HttpxClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get(self, url: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
        return await self._client.get(url, headers=headers)


@dataclass
class Scheduler:
    settings: Settings
    clock: Clock
    health: SourceHealthTracker
    _tasks: list[asyncio.Task[None]]
    _stop: asyncio.Event
    _http: httpx.AsyncClient | None

    @classmethod
    def create(cls, settings: Settings, *, clock: Clock | None = None) -> Scheduler:
        return cls(
            settings=settings,
            clock=clock or WallClock(),
            health=SourceHealthTracker(failure_threshold=settings.source_failure_threshold),
            _tasks=[],
            _stop=asyncio.Event(),
            _http=None,
        )

    async def start(self) -> None:
        if not self.settings.scheduler_enabled:
            return
        self._http = httpx.AsyncClient(timeout=30.0)
        for source in enabled_sources(self.settings):
            self._tasks.append(asyncio.create_task(self._run_source_loop(source)))

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def run_once(self, source: IngestionSource) -> None:
        await self._execute_source(source)

    def health_snapshots(self) -> list[SourceHealthSnapshot]:
        snapshots: list[SourceHealthSnapshot] = []
        for source in registered_sources():
            runtime = self.health.get(source.name)
            snapshots.append(
                SourceHealthSnapshot(
                    name=source.name,
                    enabled=source.is_enabled(self.settings),
                    status=runtime.status,
                    last_run_at=runtime.last_run_at,
                    last_success_at=runtime.last_success_at,
                    rows_last_run=runtime.rows_last_run,
                    last_error=runtime.last_error,
                    consecutive_failures=runtime.consecutive_failures,
                )
            )
        return snapshots

    async def _run_source_loop(self, source: IngestionSource) -> None:
        while not self._stop.is_set():
            started = self.clock.now()
            try:
                await self._execute_source(source)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduler loop crashed for source=%s", source.name)
            elapsed = (self.clock.now() - started).total_seconds()
            wait_for = max(0.0, source.schedule_seconds - elapsed)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait_for)
            except TimeoutError:
                continue

    async def _execute_source(self, source: IngestionSource) -> None:
        request_id = _tick_request_id(source.name)
        started_at = self.clock.now()
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=30.0)
        try:
            with shared_session(self.settings) as session:
                locations = load_locations(session)
                markets = load_markets(session)
            ctx = SourceContext(
                request_id=request_id,
                settings=self.settings,
                locations=locations,
                markets=markets,
                http=HttpxClient(self._http),
            )
            result = await source.fetch(self.clock, ctx)
            finished_at = self.clock.now()
            with shared_session(self.settings) as session:
                persist_fetch_result(
                    session,
                    source_name=source.name,
                    request_id=request_id,
                    started_at=started_at,
                    finished_at=finished_at,
                    result=result,
                )
            self.health.record_success(
                source.name,
                finished_at=finished_at,
                rows_written=result.rows_written,
                run_status=result.status,
                error_text=result.error_text,
            )
            await self._run_engine_tick(request_id)
        except Exception as exc:
            finished_at = self.clock.now()
            logger.exception("source fetch failed source=%s request_id=%s", source.name, request_id)
            self.health.record_failure(source.name, finished_at=finished_at, error=str(exc))
            if self.settings.database_url_shared:
                try:
                    with shared_session(self.settings) as session:
                        persist_fetch_result(
                            session,
                            source_name=source.name,
                            request_id=request_id,
                            started_at=started_at,
                            finished_at=finished_at,
                            result=FetchResult(
                                status=SourceRunStatus.ERROR,
                                error_text=str(exc),
                            ),
                        )
                except Exception:
                    logger.exception("failed to persist error source_run for %s", source.name)

    async def _run_engine_tick(self, request_id: str) -> None:
        from core.engine.tick import run_engine_tick

        try:
            with shared_session(self.settings) as shared, per_env_session(self.settings) as per_env:
                await run_engine_tick(
                    settings=self.settings,
                    clock=self.clock,
                    shared_session=shared,
                    per_env_session=per_env,
                    request_id=request_id,
                )
        except Exception:
            logger.exception("engine tick failed request_id=%s", request_id)
