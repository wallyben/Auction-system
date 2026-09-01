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
    assert "pid" in body
    assert "started_at" in body
    assert isinstance(body["uptime_s"], int)
    assert body["uptime_s"] >= 0
    assert body["process_role"] == "web"


def test_health_is_async_and_db_handlers_are_sync() -> None:
    """Async DB-free /health cannot queue behind sync SQLAlchemy threadpool work.

    Evidence/jobs/opportunities stay sync so SQLAlchemy does not run on the
    event loop (that pin was PR #18).
    """
    import inspect

    from app.api.routes import ops

    assert inspect.iscoroutinefunction(ops.health)
    source = inspect.getsource(ops.health)
    assert "session" not in source
    assert "get_db" not in source
    assert inspect.iscoroutinefunction(ops.health_runtime)
    runtime_src = inspect.getsource(ops.health_runtime)
    assert "session" not in runtime_src
    assert "get_db" not in runtime_src
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
