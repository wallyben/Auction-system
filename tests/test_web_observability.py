"""Request telemetry, event-loop watchdog, and bounded memory diagnostics."""

from __future__ import annotations

import asyncio
import inspect
import time

from fastapi.testclient import TestClient

from app.main import create_app
from app.web import observability as obs


def test_health_is_async_and_db_free() -> None:
    from app.api.routes import ops

    assert inspect.iscoroutinefunction(ops.health)
    source = inspect.getsource(ops.health)
    assert "session" not in source
    assert "get_db" not in source
    assert "probe_database" not in source
    assert inspect.iscoroutinefunction(ops.health_runtime)
    runtime_src = inspect.getsource(ops.health_runtime)
    assert "session" not in runtime_src
    assert "get_db" not in runtime_src


def test_request_ring_is_bounded() -> None:
    obs.reset_observability_state()
    for i in range(obs.RING_MAX + 80):
        obs._record_request({"request_id": str(i), "path": "/health", "method": "GET", "status": 200})
    assert len(obs._ring) == obs.RING_MAX
    assert obs._ring[0]["request_id"] == str(80)
    snap = obs.diagnostic_snapshot()
    assert snap["ring_n"] == obs.RING_MAX
    assert len(snap["last_requests"]) <= 40
    assert snap["secrets_included"] is False


def test_memory_sample_ring_is_bounded() -> None:
    obs.reset_observability_state()
    for _ in range(obs.SAMPLE_MAX + 20):
        obs._samples.append(obs.memory_sample())
    assert len(obs._samples) == obs.SAMPLE_MAX
    sample = obs.memory_sample()
    assert "rss_mb" in sample
    assert "gc_counts" in sample
    assert "in_flight" in sample
    assert "ring_n" in sample
    assert "pool" in sample


def test_telemetry_logs_start_and_end_without_secrets() -> None:
    obs.reset_observability_state()
    with TestClient(create_app()) as client:
        response = client.get(
            "/health",
            params={"code": "super-secret-oauth-code", "token": "should-not-appear"},
            headers={"Authorization": "Bearer secret-token", "Cookie": "session=abc"},
        )
    assert response.status_code == 200
    last = [r for r in obs.recent_requests() if r["path"] == "/health"]
    assert last
    entry = last[-1]
    assert entry["method"] == "GET"
    assert entry["path"] == "/health"
    assert "?" not in entry["path"]
    blob = str(obs.recent_requests())
    for forbidden in (
        "super-secret-oauth-code",
        "should-not-appear",
        "secret-token",
        "session=abc",
        "Bearer",
    ):
        assert forbidden not in blob
    assert "request_id" in entry
    assert "duration_ms" in entry
    assert "ts" in entry
    assert entry["status"] == 200


def test_oauth_callback_without_code_is_400() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/oauth/ebay/callback")
    assert response.status_code == 400
    assert response.json() == {"ok": False, "error": "missing_code"}


def test_web_diag_endpoint_is_bounded() -> None:
    obs.reset_observability_state()
    with TestClient(create_app()) as client:
        client.get("/health")
        body = client.get("/ops/web-diag").json()
    assert body["secrets_included"] is False
    assert body["ring_n"] <= obs.RING_MAX
    assert "stacks" not in body
    paths = [row.get("path") for row in body.get("last_requests") or []]
    assert "/health" in paths or "/ops/web-diag" in paths
    joined = str(body)
    assert "authorization" not in joined.lower() or body["secrets_included"] is False
    assert "refresh_token" not in joined


def test_watchdog_detects_three_second_block() -> None:
    async def _run() -> None:
        obs.reset_observability_state()
        obs.start_observability()
        try:
            await asyncio.sleep(0.4)
            time.sleep(3.2)
            await asyncio.sleep(0.8)
            stalls = obs.recent_stalls()
            assert stalls, "watchdog did not record WEB_EVENT_LOOP_STALL"
            assert stalls[-1]["lag_seconds"] >= 2.0
            assert "pid" in stalls[-1]
            assert "rss_mb" in stalls[-1]
        finally:
            obs.stop_observability()
            obs.reset_observability_state()

    asyncio.run(_run())


def test_watchdog_stack_dump_is_filename_only() -> None:
    obs.reset_observability_state()
    obs.inject_pulse_age(6.0)
    obs.force_stall_check(dump=True)
    stalls = obs.recent_stalls()
    assert stalls
    top = stalls[-1].get("top_frames") or []
    assert top, "expected stack evidence at >=5s lag"
    blob = str(top)
    assert ".py:" in blob
    assert "f_locals" not in blob
    assert "refresh_token" not in blob
    assert "Authorization" not in blob


def test_lifespan_skips_duplicate_migrations() -> None:
    source = inspect.getsource(__import__("app.main", fromlist=["lifespan"]).lifespan)
    assert "ARIE_WEB_RUN_MIGRATIONS" in source
    assert "run_startup_migrations" in source
