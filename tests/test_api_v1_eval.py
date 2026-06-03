from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.api.main import create_app
from core.db.enums import EvalWindow
from core.db.models import EvalMetricSnapshotRow
from core.ledger.seed import seed_strategies_if_needed
from core.settings import Settings


def _settings(shared_url: str, per_env_url: str) -> Settings:
    return Settings(
        REQUIRE_DBS=False,
        CONTROL_PLANE_TOKEN="dev-token",
        DATABASE_URL_SHARED=shared_url,
        DATABASE_URL_PER_ENV=per_env_url,
        SCHEDULER_ENABLED=False,
    )


def _snap(strategy: str, window: EvalWindow, computed_at: datetime, **kw: object) -> EvalMetricSnapshotRow:
    base = dict(
        n_trades=8, n_wins=5, hit_rate=0.625, brier_score=0.18, log_loss=0.55,
        pnl_cents=420, sharpe_proxy=0.5, max_drawdown_cents=-90,
        posterior_edge_mean=0.06, posterior_edge_ci_low=0.01, posterior_edge_ci_high=0.11,
        calibration_bins_jsonb=[
            {"lower": 0.5, "upper": 0.6, "predicted_mean": 0.55, "observed_freq": 0.5, "count": 4}
        ],
    )
    base.update(kw)
    return EvalMetricSnapshotRow(
        id=f"{strategy}-{window.value}-{computed_at.isoformat()}",
        strategy_name=strategy, computed_at=computed_at, window=window, **base,
    )


def test_eval_roster_empty_returns_seeded_strategies_with_null_metrics(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = api_client.get("/v1/eval", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) >= 1
    assert all(r["nTrades"] == 0 and r["hitRate"] is None for r in rows)


def test_eval_roster_and_detail_with_snapshots(
    per_env_sqlite_urls: tuple[str, str], auth_headers: dict[str, str]
) -> None:
    shared_url, per_env_url = per_env_sqlite_urls
    per_env = sessionmaker(bind=create_engine(per_env_url), expire_on_commit=False)()
    seed_strategies_if_needed(per_env, request_id="seed-eval-api")
    name = "weather_ensemble_disagreement"
    now = datetime(2026, 6, 1, tzinfo=UTC)
    per_env.add_all([
        _snap(name, EvalWindow.D7, now, n_trades=3),
        _snap(name, EvalWindow.D30, now, n_trades=8),
        _snap(name, EvalWindow.ALL, now, n_trades=20),
    ])
    per_env.commit()
    per_env.close()

    with TestClient(create_app(_settings(shared_url, per_env_url))) as client:
        roster = client.get("/v1/eval", headers=auth_headers).json()
        detail = client.get(f"/v1/eval/{name}", headers=auth_headers)

    by_name = {r["strategyName"]: r for r in roster}
    assert by_name[name]["nTrades"] == 20          # roster summarizes the ALL window
    assert detail.status_code == 200
    body = detail.json()
    assert body["strategyName"] == name
    windows = {w["window"]: w for w in body["windows"]}
    assert set(windows) == {"7d", "30d", "all"}
    assert windows["all"]["nTrades"] == 20
    assert windows["all"]["calibrationBins"][0]["predictedMean"] == 0.55


def test_eval_detail_unknown_strategy_404(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = api_client.get("/v1/eval/does_not_exist", headers=auth_headers)
    assert resp.status_code == 404


def test_eval_detail_known_strategy_no_snapshots_returns_empty_windows(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = api_client.get("/v1/eval/weather_ensemble_disagreement", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["windows"] == []


def test_eval_requires_auth(api_client: TestClient) -> None:
    assert api_client.get("/v1/eval").status_code == 401
