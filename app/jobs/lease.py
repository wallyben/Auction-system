"""Exclusive pipeline lease so scan / sold-refresh / revalue cannot overlap.

The Render service is a single uvicorn worker. CPU-bound ORM loops on the
asyncio event loop pin /health. This lease:

* admits only one heavy job at a time (in-process + DB row);
* expires so a crashed worker cannot wedge the pipeline forever;
* heartbeats while work proceeds;
* yields the event loop so /health stays responsive.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.orm import PipelineJob

logger = get_logger("arie.jobs.lease")

PIPELINE_LEASE_NAME = "pipeline"
LEASE_SECONDS = 12 * 60
YIELD_EVERY = 8

_busy = False
_busy_name = ""
_busy_job_id: str | None = None

Runner = Callable[[Session, PipelineJob], Awaitable[dict[str, Any]]]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_busy() -> bool:
    return _busy


def memory_status() -> dict[str, object]:
    return {"busy": _busy, "name": _busy_name or None, "job_id": _busy_job_id}


def current_job(session: Session) -> PipelineJob | None:
    return session.scalars(
        select(PipelineJob)
        .where(PipelineJob.status == "running")
        .order_by(PipelineJob.started_at.desc())
        .limit(1)
    ).first()


def lease_status(session: Session | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "busy": _busy,
        "name": _busy_name or None,
        "job_id": _busy_job_id,
        "lease": "idle",
    }
    if session is None:
        return payload
    job = current_job(session)
    if job is None:
        return payload
    now = _now()
    expired = bool(job.expires_at and job.expires_at <= now)
    payload.update(
        {
            "lease": "stale" if expired else "held",
            "name": job.name,
            "job_id": str(job.id),
            "trigger": job.trigger,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "heartbeat_at": job.heartbeat_at.isoformat() if job.heartbeat_at else None,
            "expires_at": job.expires_at.isoformat() if job.expires_at else None,
            "stale": expired,
        }
    )
    return payload


def try_acquire(session: Session, name: str, trigger: str) -> PipelineJob | None:
    """Acquire the global pipeline lease. Returns None if another job holds it."""
    global _busy, _busy_name, _busy_job_id
    now = _now()
    running = current_job(session)
    if running is not None:
        expires = running.expires_at
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        expired = expires is None or expires <= now
        if not expired or _busy:
            logger.info("pipeline_lease_busy", holder=running.name, requester=name)
            return None
        running.status = "failed"
        running.error = "stale_lease"
        running.finished_at = now
        running.details = {**(running.details or {}), "stale": True}
        logger.warning("pipeline_lease_stolen", previous=running.name, requester=name)
    if _busy:
        logger.info("pipeline_lease_busy_memory", holder=_busy_name, requester=name)
        return None
    job = PipelineJob(
        name=name,
        trigger=trigger,
        status="running",
        started_at=now,
        heartbeat_at=now,
        expires_at=now + timedelta(seconds=LEASE_SECONDS),
        details={"lease": PIPELINE_LEASE_NAME},
    )
    session.add(job)
    session.flush()
    _busy = True
    _busy_name = name
    _busy_job_id = str(job.id)
    logger.info("pipeline_lease_acquired", name=name, job_id=str(job.id), trigger=trigger)
    return job


def heartbeat(session: Session, job: PipelineJob) -> None:
    now = _now()
    job.heartbeat_at = now
    job.expires_at = now + timedelta(seconds=LEASE_SECONDS)
    session.flush()


def finish(
    session: Session,
    job: PipelineJob | None,
    *,
    ok: bool,
    error: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    global _busy, _busy_name, _busy_job_id
    now = _now()
    if job is not None:
        job.status = "success" if ok else "failed"
        job.finished_at = now
        job.heartbeat_at = now
        if error:
            job.error = error[:2000]
        if details:
            job.details = {**(job.details or {}), **details}
        session.flush()
    _busy = False
    _busy_name = ""
    _busy_job_id = None


def release_memory() -> None:
    global _busy, _busy_name, _busy_job_id
    _busy = False
    _busy_name = ""
    _busy_job_id = None


async def yield_loop() -> None:
    """Let /health and other HTTP handlers run on the single worker."""
    await asyncio.sleep(0)


async def maybe_yield(index: int, *, every: int = YIELD_EVERY) -> None:
    if index > 0 and index % every == 0:
        await yield_loop()


async def run_leased(
    session: Session,
    name: str,
    trigger: str,
    runner: Runner,
) -> dict[str, Any]:
    """Acquire, run, finish on the caller's session. Used by the scheduler."""
    job = try_acquire(session, name, trigger)
    if job is None:
        return {"ok": False, "reason": "busy", **lease_status(session)}
    try:
        result = await runner(session, job)
        finish(session, job, ok=True, details=result if isinstance(result, dict) else {})
        return {"ok": True, "job_id": str(job.id), **(result if isinstance(result, dict) else {})}
    except Exception as exc:
        logger.exception("pipeline_job_failed", name=name)
        finish(session, job, ok=False, error=str(exc))
        return {"ok": False, "reason": "failed", "error": str(exc), "job_id": str(job.id)}


async def dispatch_http(name: str, trigger: str, runner: Runner) -> dict[str, Any]:
    """Acquire the lease, return immediately, run work as a background task.

    The HTTP handler must not keep the request open for a full revalue/scan.
    Render's single worker otherwise cannot answer /health.
    """
    from app.db.session import get_session_factory

    factory = get_session_factory()
    session = factory()
    try:
        job = try_acquire(session, name, trigger)
        if job is None:
            payload = {"ok": False, "reason": "busy", "accepted": False, **lease_status(session)}
            payload["http_status"] = 409
            return payload
        job_id = job.id
        session.commit()
    except Exception:
        session.rollback()
        release_memory()
        raise
    finally:
        session.close()
    asyncio.create_task(_background(job_id, name, runner))
    return {
        "ok": True,
        "accepted": True,
        "status": "running",
        "job_id": str(job_id),
        "name": name,
        "http_status": 202,
    }


async def _background(job_id: uuid.UUID, name: str, runner: Runner) -> None:
    from app.db.session import get_session_factory

    session = get_session_factory()()
    job = session.get(PipelineJob, job_id)
    try:
        if job is None:
            release_memory()
            return
        result = await runner(session, job)
        session.commit()
        job = session.get(PipelineJob, job_id)
        finish(session, job, ok=True, details=result if isinstance(result, dict) else {})
        session.commit()
        logger.info("pipeline_job_done", name=name, job_id=str(job_id))
    except Exception as exc:
        session.rollback()
        job = session.get(PipelineJob, job_id)
        finish(session, job, ok=False, error=str(exc))
        session.commit()
        logger.exception("pipeline_job_failed", name=name, job_id=str(job_id))
    finally:
        if _busy_job_id == str(job_id):
            release_memory()
        session.close()


def recent_jobs(session: Session, *, limit: int = 12) -> list[dict[str, object]]:
    rows = session.scalars(select(PipelineJob).order_by(PipelineJob.started_at.desc()).limit(limit)).all()
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "trigger": row.trigger,
            "status": row.status,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "error": row.error,
        }
        for row in rows
    ]
