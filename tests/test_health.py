"""Health endpoint tests."""

import pytest
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


def test_health_and_evidence_handlers_are_sync() -> None:
    """Sync SQLAlchemy in async def pins uvicorn and times out /health."""
    import inspect

    from app.api.routes import ops

    assert not inspect.iscoroutinefunction(ops.health)
    assert not inspect.iscoroutinefunction(ops.health_db)
    assert not inspect.iscoroutinefunction(ops.health_evidence)
    assert not inspect.iscoroutinefunction(ops.health_jobs)
    assert not inspect.iscoroutinefunction(ops.list_opportunities)


def test_sold_provider_health_sync_refuses_event_loop() -> None:
    import asyncio

    from app.sold.provider import sold_provider_health_sync

    async def _inside_loop() -> None:
        with pytest.raises(RuntimeError, match="event loop"):
            sold_provider_health_sync(None)  # type: ignore[arg-type]

    asyncio.run(_inside_loop())
