"""Health endpoint behaviour for database up/down states."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.db.session import reset_engine
from app.db.url import normalize_database_url
from app.main import create_app

LOCAL_RENDER_SHAPE = "postgresql://arie:arie@127.0.0.1:5432/arie"
ENDPOINT = "https://arie.example.test/webhooks/ebay/account-deletion"
TOKEN = "a" * 32


def _reload() -> None:
    get_settings.cache_clear()
    reset_engine()


def _client(monkeypatch: pytest.MonkeyPatch, database_url: str | None) -> TestClient:
    if database_url is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("EBAY_NOTIFICATION_VERIFICATION_TOKEN", TOKEN)
    monkeypatch.setenv("EBAY_NOTIFICATION_ENDPOINT_URL", ENDPOINT)
    _reload()
    return TestClient(create_app())


def test_health_stays_lightweight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _reload()
    with _client(monkeypatch, None) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["valuation_algorithm"].startswith("2.")
    assert "git_sha" in body


def test_health_db_missing_url(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch, None) as client:
        response = client.get("/health/db")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["database"] == "down"
    assert body["reason"] == "not_configured"
    assert body["configured"] is False
    assert "password" not in str(body).lower()


def test_health_db_failed_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch, "postgresql://arie:arie@127.0.0.1:1/arie") as client:
        response = client.get("/health/db")
    assert response.status_code == 503
    body = response.json()
    assert body["database"] == "down"
    assert body["configured"] is True
    assert body["scheme"] == "postgresql"
    assert body["sqlalchemy_scheme"] == "postgresql+psycopg"
    assert body["host_present"] is True
    assert body["reason"] in {"connect_failed", "error"}
    assert "arie:arie" not in str(body)


def test_notification_health_db_down(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch, None) as client:
        response = client.get("/health/ebay-notifications")
    assert response.status_code == 200
    body = response.json()
    assert body["database"] == "down"
    assert body["processor"] == "database_unavailable"
    assert body["ready"] is False
    assert body["ready_for_ebay_challenge"] is True
    assert body["ebay_subscription_active"] is False


def _postgres_available() -> str | None:
    url = os.environ.get("TEST_DATABASE_URL", LOCAL_RENDER_SHAPE)
    try:
        engine = create_engine(
            normalize_database_url(url),
            connect_args={"connect_timeout": 2},
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return url
    except Exception:
        return None


def test_health_db_up_and_notification_health(monkeypatch: pytest.MonkeyPatch) -> None:
    url = _postgres_available()
    if url is None:
        pytest.skip("PostgreSQL is not available")
    from app.db.migrate import run_startup_migrations

    monkeypatch.setenv("DATABASE_URL", url)
    _reload()
    run_startup_migrations()
    with _client(monkeypatch, url) as client:
        db = client.get("/health/db")
        ebay = client.get("/health/ebay-notifications")
    assert db.status_code == 200
    assert db.json() == {"status": "ok", "database": "up"}
    assert ebay.status_code == 200
    body = ebay.json()
    assert body["database"] == "up"
    assert body["processor"] == "ready"
    assert body["ready"] is True
