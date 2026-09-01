"""Permanent load-health regression: web stays live while a worker job runs."""

from __future__ import annotations

import asyncio
import statistics
import threading
import time

from fastapi.testclient import TestClient

from app.jobs import worker
from app.jobs.queue import enqueue
from app.main import create_app


def _sqlite_factory():
    from sqlalchemy import create_engine
    from sqlalchemy.dialects.postgresql import JSONB, UUID
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base

    @compiles(JSONB, "sqlite")
    def _jsonb(type_, compiler, **kw):  # noqa: ARG001
        return "JSON"

    @compiles(UUID, "sqlite")
    def _uuid(type_, compiler, **kw):  # noqa: ARG001
        return "CHAR(36)"

    import app.models.orm  # noqa: F401

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_full_book_style_revalue_does_not_stall_health(monkeypatch) -> None:
    """Web /health must not time out, hang, or 5xx while a worker revalue runs.

    Production 2026-09-01: 6 zero-byte /health timeouts during a 184s worker
    revalue. This harness is the in-process equivalent: enqueue one revalue,
    block the worker, probe /health continuously.
    """
    factory = _sqlite_factory()
    monkeypatch.setattr("app.db.session.get_session_factory", lambda: factory)
    session = factory()
    enqueue(session, "revalue", "test")
    session.commit()

    async def slow_execute(sess, job):
        await asyncio.sleep(1.2)
        return {"ok": True, "revalued": 1}

    monkeypatch.setattr(worker, "execute_job", slow_execute)
    errors: list[str] = []

    def run_worker() -> None:
        try:
            asyncio.run(worker.process_once(factory(), "load-health-worker"))
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

    thread = threading.Thread(target=run_worker)
    thread.start()
    time.sleep(0.05)
    probes: list[dict[str, object]] = []
    started_ats: set[str] = set()
    with TestClient(create_app()) as client:
        deadline = time.time() + 2.0
        while time.time() < deadline:
            t0 = time.perf_counter()
            response = client.get("/health")
            dt = time.perf_counter() - t0
            body = response.json() if response.content else {}
            probes.append(
                {
                    "status": response.status_code,
                    "latency_s": dt,
                    "nbytes": len(response.content),
                    "pid": body.get("pid"),
                    "started_at": body.get("started_at"),
                }
            )
            if body.get("started_at"):
                started_ats.add(str(body["started_at"]))
            time.sleep(0.05)
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert errors == []
    assert len(probes) >= 8
    assert all(p["status"] == 200 for p in probes)
    assert all(int(p["nbytes"]) > 0 for p in probes)  # type: ignore[arg-type]
    latencies = [float(p["latency_s"]) for p in probes]
    assert max(latencies) < 0.5
    assert statistics.median(latencies) < 0.25
    assert len(started_ats) == 1
    session.close()
