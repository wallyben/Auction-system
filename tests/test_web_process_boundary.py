"""Web is HTTP-only. Worker owns scheduler and pipeline execution."""

from __future__ import annotations

import inspect
import os

from fastapi.testclient import TestClient

from app.jobs import scheduler, worker
from app.jobs.queue import PIPELINE_JOBS, claim_next, enqueue
from app.main import create_app, lifespan


def test_web_lifespan_does_not_start_scheduler() -> None:
    source = inspect.getsource(lifespan)
    assert "start_scheduler" not in source
    assert "AsyncIOScheduler" not in inspect.getsource(create_app)
    from app import main as main_mod

    assert "start_scheduler" not in inspect.getsource(main_mod)


def test_web_process_refuses_scheduler(monkeypatch) -> None:
    monkeypatch.setenv("ARIE_PROCESS", "web")
    monkeypatch.setenv("ARIE_ALLOW_SCHEDULER", "1")
    try:
        scheduler.start_scheduler()
        snap = scheduler.local_scheduler_snapshot()
        assert snap["running"] is False
        assert scheduler._scheduler is None
    finally:
        scheduler.stop_scheduler()


def test_worker_process_starts_and_stops_scheduler(monkeypatch) -> None:
    monkeypatch.setenv("ARIE_PROCESS", "worker")
    monkeypatch.setenv("ARIE_ALLOW_SCHEDULER", "1")
    try:
        scheduler.start_scheduler()
        snap = scheduler.local_scheduler_snapshot()
        assert snap["running"] is True
        ids = {job["id"] for job in snap["jobs"]}  # type: ignore[union-attr]
        assert "scan-live-sources" in ids
        assert "ebay-deletion-retry" in ids
        assert "daily-self-audit" in ids
        assert "owner-sold-ingest" in ids
        assert snap["owner"] == "worker"
        scheduler.start_scheduler()
        assert scheduler.local_scheduler_snapshot()["running"] is True
        scheduler.stop_scheduler()
        scheduler.start_scheduler()
        assert scheduler.local_scheduler_snapshot()["running"] is True
    finally:
        scheduler.stop_scheduler()
        assert scheduler.local_scheduler_snapshot()["running"] is False


def test_worker_runtime_starts_scheduler() -> None:
    source = inspect.getsource(worker.run_forever)
    assert "start_scheduler()" in source
    assert "stop_scheduler()" in source
    assert source.index("start_scheduler()") < source.index("start_process_heartbeat")


def test_health_and_runtime_are_db_free() -> None:
    from app.api.routes import ops

    for fn in (ops.health, ops.health_runtime):
        source = inspect.getsource(fn)
        assert "session" not in source
        assert "get_db" not in source
        assert "probe_database" not in source
        assert "lease_status" not in source


def test_health_reports_web_process_role() -> None:
    with TestClient(create_app()) as client:
        body = client.get("/health").json()
        runtime = client.get("/health/runtime").json()
    assert body["process_role"] == "web"
    assert runtime["process_role"] == "web"
    assert "rss_mb" in runtime
    assert runtime["pid"] == os.getpid() or isinstance(runtime["pid"], int)


def test_pipeline_jobs_include_scheduler_owned_work() -> None:
    assert "deletion-retry" in PIPELINE_JOBS
    assert "self-audit" in PIPELINE_JOBS
    assert "sold-ingest" in PIPELINE_JOBS
    source = inspect.getsource(worker.execute_job)
    assert 'name == "deletion-retry"' in source
    assert 'name == "self-audit"' in source
    assert 'name == "sold-ingest"' in source


def test_scheduler_enqueue_skips_when_busy(monkeypatch) -> None:
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
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr("app.jobs.scheduler.get_session_factory", lambda: factory)
    session = factory()
    enqueue(session, "revalue", "test")
    session.commit()
    skipped = scheduler._enqueue_or_skip("scan", "scheduler", {"limit": 8})
    assert skipped.get("reason") == "busy"
    skipped_light = scheduler._enqueue_or_skip("deletion-retry", "scheduler", {})
    assert skipped_light.get("reason") == "busy"
    claimed = claim_next(session, "w1")
    assert claimed is not None
    assert claimed.name == "revalue"
    session.close()
