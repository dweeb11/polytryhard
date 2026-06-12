from fastapi.testclient import TestClient


def test_audit_lists_recent_events(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    api_client.post(
        "/v1/strategies/weather_ensemble_disagreement/pause",
        headers=auth_headers,
        json={"reason": "audit test"},
    )
    response = api_client.get(
        "/v1/audit",
        headers=auth_headers,
        params={"action": "pause_strategy"},
    )
    assert response.status_code == 200
    events = response.json()
    assert len(events) >= 1
    assert events[0]["action"] == "pause_strategy"
