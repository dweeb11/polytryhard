from fastapi.testclient import TestClient


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


def test_list_strategies_exposes_effective_soak_config(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = api_client.get("/v1/strategies", headers=auth_headers)
    assert response.status_code == 200
    rows = {row["name"]: row for row in response.json()}
    ensemble = rows["weather_ensemble_disagreement"]["config"]
    stale = rows["weather_stale_quote"]["config"]
    assert ensemble["confidenceFloor"] == 0.55
    assert ensemble["disagreementThreshold"] == 2.0
    assert ensemble["spreadMarginMultiplier"] == 1.5
    assert ensemble["exposureCapPct"] == 0.10
    assert ensemble["correlationCapPct"] == 0.05
    assert stale["confidenceFloor"] == 0.55
    assert stale["wideSpreadThreshold"] == 0.08
    assert stale["exposureCapPct"] == 0.10
    assert stale["correlationCapPct"] == 0.05


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


def test_invalid_token_is_rejected(api_client: TestClient) -> None:
    response = api_client.get(
        "/v1/strategies",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401
