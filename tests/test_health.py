"""Health endpoint tests."""

from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_returns_ok() -> None:
    """Health endpoint should return expected service status."""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["valuation_algorithm"].startswith("2.")
    assert "git_sha" in body
