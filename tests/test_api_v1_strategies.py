from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.db.models import SignalRow
from core.domain.enums import SignalOutcome
from core.utils.time import utc_now


def test_list_strategies_requires_auth(api_client: TestClient) -> None:
    response = api_client.get("/v1/strategies")
    assert response.status_code == 401


def test_list_strategies_returns_seeded_rows(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = api_client.get("/v1/strategies", headers=auth_headers)
    assert response.status_code == 200
    names = {row["name"] for row in response.json()}
    assert "weather_ensemble_disagreement" in names
    assert "weather_stale_quote" in names


def test_deposit_mutation_updates_bankroll(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    name = "weather_ensemble_disagreement"
    before = api_client.get(f"/v1/strategies/{name}", headers=auth_headers).json()
    response = api_client.post(
        f"/v1/strategies/{name}/deposit",
        headers=auth_headers,
        json={"amountCents": 500, "reason": "api test"},
    )
    assert response.status_code == 200
    after = api_client.get(f"/v1/strategies/{name}", headers=auth_headers).json()
    assert after["bankrollCents"] == before["bankrollCents"] + 500


def test_set_starting_bankroll_updates_pre_soak_baseline(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    name = "weather_ensemble_disagreement"
    response = api_client.post(
        f"/v1/strategies/{name}/set-starting-bankroll",
        headers=auth_headers,
        json={"amountCents": 25000, "reason": "pre-soak baseline"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["bankrollCents"] == 25_000
    assert payload["initialDepositCents"] == 25_000
    assert payload["bankrollHwmCents"] == 25_000
    assert payload["config"]["minBankrollCents"] == 25_000
    assert payload["config"]["minTradeableBankrollCents"] == 5_000


def test_set_starting_bankroll_rejects_after_signal(
    api_client: TestClient,
    auth_headers: dict[str, str],
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    _, per_env_url = per_env_sqlite_urls
    engine = create_engine(per_env_url)
    with Session(engine) as session:
        session.add(
            SignalRow(
                id="signal-api",
                strategy_name="weather_ensemble_disagreement",
                ticker="KXTEST",
                evaluated_at=utc_now(),
                prob_yes=Decimal("0.55"),
                confidence=Decimal("0.55"),
                features_snapshot_jsonb={},
                market_state_jsonb={},
                outcome=SignalOutcome.REJECTED_STALE_INPUTS,
                rejection_reason="test",
            )
        )
        session.commit()

    response = api_client.post(
        "/v1/strategies/weather_ensemble_disagreement/set-starting-bankroll",
        headers=auth_headers,
        json={"amountCents": 25000, "reason": "too late"},
    )
    assert response.status_code == 400
    assert "before signals" in response.json()["detail"]


def test_invalid_token_is_rejected(api_client: TestClient) -> None:
    response = api_client.get(
        "/v1/strategies",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401
