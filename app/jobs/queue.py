"""Postgres-backed pipeline queue.

The web process enqueues and returns HTTP 202. A dedicated worker claims jobs
with compare-and-swap. At most one heavy pipeline job may be running.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.orm import PipelineJob, PipelineWorker

logger = get_logger("arie.jobs.queue")

HEAVY_JOBS = frozenset({"scan", "revalue", "sold-revalidate", "sold-refresh"})
LEASE_SECONDS = 12 * 60
WORKER_STALE_SECONDS = 30
PIPELINE_LEASE_NAME = "pipeline"

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def lease_status(session: Session | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "busy": False,
        "name": None,
        "job_id": None,
        "lease": "idle",
        "worker": None,
    }
    if session is None:
        return payload
    running = current_running(session)
    queued = session.scalars(
        select(PipelineJob).where(PipelineJob.status == STATUS_QUEUED).order_by(PipelineJob.created_at.desc())
    ).first()
    worker = newest_worker(session)
    if worker is not None:
        age = (_now() - _aware(worker.heartbeat_at)).total_seconds()
        payload["worker"] = {
            "worker_id": worker.worker_id,
            "heartbeat_at": worker.heartbeat_at.isoformat() if worker.heartbeat_at else None,
            "connected": age <= WORKER_STALE_SECONDS,
            "age_seconds": int(age),
        }
    if running is not None:
        expired = bool(running.expires_at and _aware(running.expires_at) <= _now())
        payload.update(
            {
                "busy": not expired,
                "name": running.name,
                "job_id": str(running.id),
                "trigger": running.trigger,
                "started_at": running.started_at.isoformat() if running.started_at else None,
                "heartbeat_at": running.heartbeat_at.isoformat() if running.heartbeat_at else None,
                "expires_at": running.expires_at.isoformat() if running.expires_at else None,
                "lease": "stale" if expired else "held",
                "stale": expired,
                "claimed_by": running.claimed_by,
            }
        )
        return payload
    if queued is not None:
        payload.update(
            {
                "busy": True,
                "name": queued.name,
                "job_id": str(queued.id),
                "lease": "queued",
                "trigger": queued.trigger,
            }
        )
    return payload


def newest_worker(session: Session) -> PipelineWorker | None:
    return session.scalars(select(PipelineWorker).order_by(PipelineWorker.heartbeat_at.desc()).limit(1)).first()


def current_running(session: Session) -> PipelineJob | None:
    return session.scalars(
        select(PipelineJob)
        .where(PipelineJob.status == STATUS_RUNNING)
        .order_by(PipelineJob.started_at.desc())
        .limit(1)
    ).first()


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return _now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def recover_stale(session: Session) -> list[str]:
    """Expired running jobs become queued again so another worker can claim them."""
    now = _now()
    recovered: list[str] = []
    rows = session.scalars(select(PipelineJob).where(PipelineJob.status == STATUS_RUNNING)).all()
    for job in rows:
        expires = _aware(job.expires_at)
        if expires <= now:
            job.status = STATUS_QUEUED
            job.claimed_by = None
            job.error = "stale_requeued"
            extras = dict(job.details or {})
            extras["reclaims"] = int(extras.get("reclaims") or 0) + 1
            extras["last_stale_at"] = now.isoformat()
            job.details = extras
            recovered.append(str(job.id))
            logger.warning("pipeline_job_stale_requeued", job_id=str(job.id), name=job.name)
    if recovered:
        session.flush()
    return recovered


def _open_pipeline_job(session: Session) -> PipelineJob | None:
    recover_stale(session)
    running = current_running(session)
    if running is not None and _aware(running.expires_at) > _now():
        return running
    return session.scalars(
        select(PipelineJob).where(PipelineJob.status == STATUS_QUEUED).order_by(PipelineJob.created_at.asc()).limit(1)
    ).first()


def enqueue(
    session: Session,
    name: str,
    trigger: str,
    payload: dict[str, Any] | None = None,
) -> tuple[PipelineJob | None, dict[str, Any]]:
    """Insert a queued job. Does not execute work. One open pipeline job at a time."""
    if name not in HEAVY_JOBS:
        return None, {"ok": False, "reason": "unknown_job", "name": name}
    open_job = _open_pipeline_job(session)
    if open_job is not None:
        status = lease_status(session)
        return None, {"ok": False, "reason": "busy", "accepted": False, **status}
    job = PipelineJob(
        name=name,
        trigger=trigger,
        status=STATUS_QUEUED,
        details={"lease": PIPELINE_LEASE_NAME, "payload": payload or {}},
    )
    session.add(job)
    session.flush()
    logger.info("pipeline_job_enqueued", name=name, job_id=str(job.id), trigger=trigger)
    return job, {"ok": True, "accepted": True, "status": STATUS_QUEUED, "job_id": str(job.id), "name": name}


def enqueue_http(name: str, trigger: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.db.session import get_session_factory

    factory = get_session_factory()
    session = factory()
    try:
        job, result = enqueue(session, name, trigger, payload)
        if job is None:
            result["http_status"] = 409
            session.commit()
            return result
        session.commit()
        result["http_status"] = 202
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def claim_next(session: Session, worker_id: str) -> PipelineJob | None:
    """Claim the oldest queued job if no running job holds the lease."""
    recover_stale(session)
    running = current_running(session)
    if running is not None and _aware(running.expires_at) > _now():
        return None
    queued = session.scalars(
        select(PipelineJob).where(PipelineJob.status == STATUS_QUEUED).order_by(PipelineJob.created_at.asc()).limit(1)
    ).first()
    if queued is None:
        return None
    now = _now()
    result = session.execute(
        update(PipelineJob)
        .where(PipelineJob.id == queued.id, PipelineJob.status == STATUS_QUEUED)
        .values(
            status=STATUS_RUNNING,
            claimed_by=worker_id,
            started_at=now,
            heartbeat_at=now,
            expires_at=now + timedelta(seconds=LEASE_SECONDS),
            error=None,
        )
    )
    if int(result.rowcount or 0) != 1:
        session.flush()
        return None
    session.flush()
    claimed = session.get(PipelineJob, queued.id)
    logger.info("pipeline_job_claimed", job_id=str(queued.id), name=queued.name, worker_id=worker_id)
    return claimed


def heartbeat(session: Session, job: PipelineJob) -> None:
    now = _now()
    job.heartbeat_at = now
    job.expires_at = now + timedelta(seconds=LEASE_SECONDS)
    if job.claimed_by:
        beat_worker(session, job.claimed_by)
    session.flush()


def finish(
    session: Session,
    job: PipelineJob | None,
    *,
    ok: bool,
    error: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    now = _now()
    if job is None:
        return
    job.status = STATUS_SUCCESS if ok else STATUS_FAILED
    job.finished_at = now
    job.heartbeat_at = now
    if error:
        job.error = error[:2000]
    if details:
        job.details = {**(job.details or {}), **details}
    session.flush()


def beat_worker(session: Session, worker_id: str, *, hostname: str = "", pid: int = 0) -> None:
    now = _now()
    row = session.scalars(select(PipelineWorker).where(PipelineWorker.worker_id == worker_id)).first()
    if row is None:
        row = PipelineWorker(
            worker_id=worker_id,
            hostname=hostname or os.uname().nodename,
            pid=pid or os.getpid(),
            heartbeat_at=now,
            started_at=now,
        )
        session.add(row)
    else:
        row.heartbeat_at = now
        row.hostname = hostname or row.hostname
        row.pid = pid or row.pid
    session.flush()


def recent_jobs(session: Session, *, limit: int = 12) -> list[dict[str, object]]:
    rows = session.scalars(select(PipelineJob).order_by(PipelineJob.created_at.desc()).limit(limit)).all()
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "trigger": row.trigger,
            "status": row.status,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "error": row.error,
            "claimed_by": row.claimed_by,
        }
        for row in rows
    ]


def new_worker_id() -> str:
    return uuid.uuid4().hex[:16]
