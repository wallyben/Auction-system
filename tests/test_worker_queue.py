"""Web enqueues; a dedicated worker runs heavy pipeline jobs."""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.jobs import lease, queue, scheduler, worker
from app.jobs.queue import claim_next, enqueue, finish, recover_stale
from app.main import create_app


@compiles(JSONB, "sqlite")
def _jsonb(type_, compiler, **kw):  # noqa: ARG001
    return "JSON"


@compiles(UUID, "sqlite")
def _uuid(type_, compiler, **kw):  # noqa: ARG001
    return "CHAR(36)"


def _factory():
    import app.models.orm  # noqa: F401

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)


def test_start_scripts_label_web_vs_worker() -> None:
    from pathlib import Path

    web = Path("scripts/start.sh").read_text()
    worker = Path("scripts/start-worker.sh").read_text()
    assert 'ARIE_PROCESS="${ARIE_PROCESS:-web}"' in web
    assert "uvicorn" in web
    assert 'ARIE_PROCESS="${ARIE_PROCESS:-worker}"' in worker
    assert "python -m app.jobs.worker" in worker
    assert "uvicorn" not in worker


def test_dispatch_http_enqueues_and_ignores_runners() -> None:
    source = inspect.getsource(lease.dispatch_http)
    assert "enqueue_http" in source
    assert "to_thread" in source
    assert "runner" not in source.split("return", 1)[-1] or "ignored" in source.lower()
    assert "await runner" not in source


def test_scheduler_enqueues_rather_than_executing_heavy_jobs() -> None:
    scan_src = inspect.getsource(scheduler._scheduled_scan)
    refresh_src = inspect.getsource(scheduler._scheduled_sold_refresh)
    revalue_src = inspect.getsource(scheduler._scheduled_revalue)
    for src in (scan_src, refresh_src, revalue_src):
        assert "_enqueue_or_skip" in src
        assert "to_thread" in src
        assert "run_scan" not in src
        assert "revalue_all_active" not in src
        assert "refresh_sold_evidence" not in src


def test_queue_exclusivity_and_no_duplicate_execution() -> None:
    factory = _factory()
    session = factory()
    first, result = enqueue(session, "revalue", "test")
    assert result["ok"] is True
    busy, busy_result = enqueue(session, "scan", "test")
    assert busy is None
    assert busy_result["reason"] == "busy"
    one = claim_next(session, "w1")
    two = claim_next(session, "w2")
    assert one is not None
    assert two is None
    assert one.id == first.id
    finish(session, one, ok=True)
    again = claim_next(session, "w2")
    assert again is None
    session.close()


def test_two_workers_cannot_claim_the_same_job() -> None:
    factory = _factory()
    session = factory()
    job, _ = enqueue(session, "scan", "test")
    session.commit()
    a = factory()
    b = factory()
    first = claim_next(a, "w-a")
    a.commit()
    second = claim_next(b, "w-b")
    b.commit()
    assert first is not None
    assert first.id == job.id
    assert second is None
    a.close()
    b.close()
    session.close()


def test_job_lease_heartbeat_does_not_refresh_worker() -> None:
    """Pipeline job lease and worker process liveness are separate rows."""
    from app.jobs.queue import beat_worker, heartbeat, newest_worker
    from app.jobs.queue import WORKER_STALE_SECONDS

    factory = _factory()
    session = factory()
    beat_worker(session, "lease-worker", pid=1)
    job, _ = enqueue(session, "revalue", "test")
    claimed = claim_next(session, "lease-worker")
    assert claimed is not None
    worker = newest_worker(session)
    assert worker is not None
    worker.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=WORKER_STALE_SECONDS + 5)
    session.flush()
    before_job_expiry = claimed.expires_at
    heartbeat(session, claimed)
    worker = newest_worker(session)
    age = (datetime.now(timezone.utc) - worker.heartbeat_at).total_seconds()
    assert age > WORKER_STALE_SECONDS
    status = queue.lease_status(session)
    assert status["worker"]["connected"] is False
    assert claimed.expires_at > before_job_expiry
    assert status["lease"] == "held"
    session.close()


def test_stale_job_lease_can_still_be_stolen() -> None:
    factory = _factory()
    session = factory()
    job, _ = enqueue(session, "revalue", "test")
    claimed = claim_next(session, "crashed-worker")
    assert claimed is not None
    claimed.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    session.flush()
    recovered = recover_stale(session)
    assert str(job.id) in recovered
    stolen = claim_next(session, "recovered-worker")
    assert stolen is not None
    assert stolen.id == job.id
    assert stolen.claimed_by == "recovered-worker"
    finish(session, stolen, ok=True)
    session.close()


def test_worker_death_becomes_stale_while_job_lease_held() -> None:
    from app.jobs.queue import beat_worker, newest_worker
    from app.jobs.queue import WORKER_STALE_SECONDS

    factory = _factory()
    session = factory()
    beat_worker(session, "dead-worker", pid=9)
    job, _ = enqueue(session, "scan", "test")
    claimed = claim_next(session, "dead-worker")
    assert claimed is not None
    worker = newest_worker(session)
    worker.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=WORKER_STALE_SECONDS + 1)
    session.flush()
    status = queue.lease_status(session)
    assert status["lease"] == "held"
    assert status["claimed_by"] == "dead-worker"
    assert status["worker"]["connected"] is False
    session.close()


def test_process_heartbeat_survives_45s_blocking_job() -> None:
    """Worker liveness must not depend on execute_job calling job heartbeat.

    Live scan 2026-09-01 ran >30s with lease held and worker_connected flipped
    false. A 45s blocking execute_job plus the process heartbeat thread must
    keep connected=true the whole time.
    """
    from app.jobs.queue import newest_worker
    from app.jobs.queue import WORKER_STALE_SECONDS
    from app.jobs.worker import start_process_heartbeat

    factory = _factory()
    session = factory()
    enqueue(session, "scan", "test")
    session.commit()
    halt = start_process_heartbeat("hb-worker", interval_seconds=10, factory=factory)
    time.sleep(0.2)
    connected_samples: list[bool] = []
    errors: list[str] = []

    async def blocking_execute(sess, job):
        deadline = time.time() + 45
        while time.time() < deadline:
            time.sleep(5)
            probe = factory()
            try:
                status = queue.lease_status(probe)
                connected_samples.append(bool((status.get("worker") or {}).get("connected")))
            finally:
                probe.close()
        return {"ok": True}

    import app.jobs.worker as worker_mod

    original = worker_mod.execute_job
    worker_mod.execute_job = blocking_execute

    def run_worker() -> None:
        try:
            asyncio.run(worker.process_once(factory(), "hb-worker"))
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

    try:
        thread = threading.Thread(target=run_worker)
        thread.start()
        thread.join(timeout=60)
        assert not thread.is_alive()
        assert errors == []
        assert connected_samples
        assert all(connected_samples), connected_samples
        assert len(connected_samples) >= 8
        live = newest_worker(session)
        assert live is not None
        hb = live.heartbeat_at
        if hb.tzinfo is None:
            hb = hb.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - hb).total_seconds()
        assert age < WORKER_STALE_SECONDS
    finally:
        halt.set()
        worker_mod.execute_job = original
        session.close()


def test_health_stays_responsive_while_worker_revalues(monkeypatch) -> None:
    factory = _factory()
    session = factory()
    enqueue(session, "revalue", "test")
    session.commit()

    async def slow_execute(sess, job):
        await asyncio.sleep(0.8)
        return {"ok": True, "revalued": 1}

    monkeypatch.setattr(worker, "execute_job", slow_execute)
    errors: list[str] = []

    def run_worker() -> None:
        try:
            asyncio.run(worker.process_once(factory(), "health-worker"))
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

    thread = threading.Thread(target=run_worker)
    thread.start()
    time.sleep(0.05)
    latencies: list[float] = []
    with TestClient(create_app()) as client:
        for _ in range(12):
            started = time.perf_counter()
            response = client.get("/health")
            latencies.append(time.perf_counter() - started)
            assert response.status_code == 200
            assert response.json()["status"] == "ok"
            time.sleep(0.05)
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert errors == []
    assert latencies
    assert max(latencies) < 0.5
    assert sum(1 for item in latencies if item < 0.25) == len(latencies)
    session.close()


def test_http_ops_revalue_returns_quickly(monkeypatch) -> None:
    factory = _factory()

    monkeypatch.setattr("app.db.session.get_session_factory", lambda: factory)
    started = time.perf_counter()
    with TestClient(create_app()) as client:
        response = client.post("/ops/revalue")
    elapsed = time.perf_counter() - started
    assert response.status_code == 202
    body = response.json()
    assert body.get("accepted") is True
    assert elapsed < 2.0
    session = factory()
    from app.models.orm import PipelineJob

    jobs = session.query(PipelineJob).all() if hasattr(session, "query") else []
    from sqlalchemy import select

    jobs = list(session.scalars(select(PipelineJob)).all())
    assert len(jobs) == 1
    assert jobs[0].status == "queued"
    assert jobs[0].name == "revalue"
    session.close()
