from fastapi.testclient import TestClient


def test_kill_switch_blocks_deposit(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    pause = api_client.post(
        "/v1/system/pause",
        headers=auth_headers,
        json={"reason": "incident"},
    )
    assert pause.status_code == 204
    system = api_client.get("/v1/system", headers=auth_headers).json()
    assert system["state"] == "paused"

    deposit = api_client.post(
        "/v1/strategies/weather_ensemble_disagreement/deposit",
        headers=auth_headers,
        json={"amountCents": 100, "reason": "blocked"},
    )
    assert deposit.status_code == 400

    decommission = api_client.post(
        "/v1/strategies/weather_ensemble_disagreement/decommission",
        headers=auth_headers,
        json={"reason": "blocked"},
    )
    assert decommission.status_code == 400
    assert decommission.json()["detail"] == "System kill switch is active"

    resume = api_client.post(
        "/v1/system/resume",
        headers=auth_headers,
        json={"reason": "cleared"},
    )
    assert resume.status_code == 204
    assert api_client.get("/v1/system", headers=auth_headers).json()["state"] == "active"
