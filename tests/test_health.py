"""Service foundation API tests."""

from fastapi.testclient import TestClient

from agent_patterns.app import create_app
from agent_patterns.config import Settings


def test_health_reports_service_metadata() -> None:
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["environment"] == "test"
    assert response.headers["x-request-id"]


def test_request_id_is_propagated() -> None:
    app = create_app(Settings(environment="test"))

    with TestClient(app) as client:
        response = client.get("/ready", headers={"x-request-id": "trace-me"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "trace-me"
    assert response.json() == {"status": "ready", "checks": {"api": "up"}}
