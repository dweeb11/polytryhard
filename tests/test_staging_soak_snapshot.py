import importlib.util
import io
import json
import sys
import urllib.error
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from core.api.main import create_app
from core.scheduler import CycleHealth, Scheduler
from core.settings import Settings


def _load_snapshot_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "staging_soak_snapshot.py"
    spec = importlib.util.spec_from_file_location("staging_soak_snapshot", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_snapshot = _load_snapshot_script()
ApiClient = _snapshot.ApiClient
cents = _snapshot.cents
fetch_snapshot = _snapshot.fetch_snapshot
render_snapshot = _snapshot.render_snapshot


@dataclass(frozen=True)
class LocalApiClient:
    client: TestClient
    token: str = "dev-token"

    def get(self, path: str, params: dict[str, str] | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.token}"} if path.startswith("/v1") else {}
        response = self.client.get(path, params=params or {}, headers=headers)
        data = response.json()
        if response.status_code == 503 and isinstance(data, dict):
            return data
        response.raise_for_status()
        return data


def test_cents_formats_none_and_values() -> None:
    assert cents(None) == "$0.00"
    assert cents(12345) == "$123.45"


def test_api_client_returns_json_on_degraded_healthz() -> None:
    payload = {
        "status": "degraded",
        "db_shared": "ok",
        "db_per_env": "ok",
        "scheduler_cycle": {"status": "error", "last_success_at": None},
    }
    error = urllib.error.HTTPError(
        url="http://test/healthz",
        code=503,
        msg="Service Unavailable",
        hdrs=Message(),
        fp=io.BytesIO(json.dumps(payload).encode()),
    )
    with patch("urllib.request.urlopen", side_effect=error):
        result = ApiClient("http://test", "token").get("/healthz")
    assert result == payload


def test_render_snapshot_includes_operational_sections() -> None:
    output = render_snapshot(
        {
            "captured_at": "2026-06-04T00:00:00+00:00",
            "health": {
                "status": "ok",
                "db_shared": "ok",
                "db_per_env": "ok",
                "scheduler_cycle": {
                    "status": "ok",
                    "last_success_at": "2026-06-04T00:00:00Z",
                },
            },
            "sources": [
                {
                    "name": "kalshi_markets",
                    "enabled": True,
                    "status": "ok",
                    "lastSuccessAt": "2026-06-04T00:00:00Z",
                    "rowsLastRun": 10,
                    "lastError": None,
                }
            ],
            "strategies": [
                {
                    "name": "weather_ensemble_disagreement",
                    "state": "active",
                    "bankrollCents": 25000,
                    "bankrollHwmCents": 25000,
                    "kellyFraction": 0.25,
                }
            ],
            "signals": [
                {
                    "strategyName": "weather_ensemble_disagreement",
                    "outcome": "order_placed",
                },
                {
                    "strategyName": "weather_ensemble_disagreement",
                    "outcome": "rejected_stale_inputs",
                },
            ],
            "positions": [
                {
                    "strategyName": "weather_ensemble_disagreement",
                    "status": "open",
                    "realizedPnlCents": None,
                    "unrealizedPnlCents": 125,
                }
            ],
            "cash_events": {
                "weather_ensemble_disagreement": [
                    {
                        "kind": "deposit",
                        "amountCents": 25000,
                        "balanceAfterCents": 25000,
                    }
                ]
            },
            "eval_roster": [
                {
                    "strategyName": "weather_ensemble_disagreement",
                    "nTrades": 1,
                    "hitRate": 1.0,
                    "brierScore": 0.1,
                    "pnlCents": 125,
                    "posteriorEdgeCiLow": -0.02,
                }
            ],
        }
    )

    assert "shared_db=ok" in output
    assert "per_env_db=ok" in output
    assert "Health" in output
    assert "Sources" in output
    assert "Signals (latest 2)" in output
    assert "Positions (latest 1)" in output
    assert "Recent cash events" in output
    assert "Eval roster" in output
    assert "weather_ensemble_disagreement" in output
    assert "order_placed" in output
    assert "$250.00" in output


def test_render_snapshot_shows_degraded_banner() -> None:
    output = render_snapshot(
        {
            "captured_at": "2026-06-04T00:00:00+00:00",
            "health": {
                "status": "degraded",
                "db_shared": "ok",
                "db_per_env": "ok",
            },
            "sources": [],
            "strategies": [],
            "signals": [],
            "positions": [],
            "eval_roster": [],
            "cash_events": {},
        }
    )

    assert "DEGRADED" in output
    assert "shared_db=ok" in output


def test_fetch_snapshot_against_local_api(api_client: TestClient) -> None:
    snapshot = fetch_snapshot(LocalApiClient(client=api_client))
    output = render_snapshot(snapshot)

    assert snapshot["health"]["db_shared"] in {"ok", "down", "unconfigured"}
    assert f"shared_db={snapshot['health']['db_shared']}" in output
    assert "Health" in output
    assert isinstance(snapshot["strategies"], list)
    assert isinstance(snapshot["signals"], list)


def test_fetch_snapshot_survives_degraded_healthz(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    shared_url, per_env_url = per_env_sqlite_urls
    settings = Settings(
        REQUIRE_DBS=False,
        CONTROL_PLANE_TOKEN="dev-token",
        DATABASE_URL_SHARED=shared_url,
        DATABASE_URL_PER_ENV=per_env_url,
        SCHEDULER_ENABLED=False,
    )
    app = create_app(settings)
    app.state.scheduler = Scheduler.create(settings)
    app.state.scheduler.cycle_health = CycleHealth(last_cycle_error="engine tick failed")
    client = TestClient(app)

    snapshot = fetch_snapshot(LocalApiClient(client=client))
    output = render_snapshot(snapshot)

    assert snapshot["health"]["status"] == "degraded"
    assert "DEGRADED" in output
    assert "shared_db=ok" in output
    assert "Health" in output
