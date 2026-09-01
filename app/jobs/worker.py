"""Dedicated pipeline worker. Never run inside the web process.

    python -m app.jobs.worker
"""

from __future__ import annotations

import asyncio
import os
import signal
import threading
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.core.logging import configure_logging, get_logger
from app.jobs.queue import beat_worker, claim_next, finish, heartbeat, new_worker_id
from app.models.orm import PipelineJob

logger = get_logger("arie.jobs.worker")

# Process liveness is independent of pipeline-job lease heartbeats.
# 10s beat / 30s stale: three missed beats mark the process dead.
WORKER_HEARTBEAT_SECONDS = 10

_STOP = False


def _request_stop(*_args: object) -> None:
    global _STOP
    _STOP = True


async def execute_job(session: Session, job: PipelineJob) -> dict[str, Any]:
    payload = dict((job.details or {}).get("payload") or {})
    name = job.name
    if name == "scan":
        from app.pipeline.service import run_scan

        scan = await run_scan(
            session,
            source_id=payload.get("source_id"),
            query=payload.get("query"),
            trigger=job.trigger or "worker",
            limit=int(payload.get("limit") or 12),
        )
        return {
            "listings_seen": scan.listings_seen,
            "opportunities_written": scan.opportunities_written,
            "status": scan.status,
            "error": scan.error,
        }
    if name == "revalue":
        from app.pipeline.service import revalue_all_active
        from app.valuation.version import VALUATION_ALGORITHM_VERSION

        reason = str(payload.get("reason") or f"worker:{VALUATION_ALGORITHM_VERSION}")
        return await revalue_all_active(session, reason=reason, job=job)
    if name == "sold-revalidate":
        from app.sold.refresh import revalidate_stored_sold_evidence, revalue_matching

        summary = await revalidate_stored_sold_evidence(session, job=job)
        changed = set(summary.get("changed_product_ids") or [])
        revalued = await revalue_matching(session, changed, job=job) if changed else 0
        return {**summary, "revalued": revalued}
    if name == "sold-refresh":
        from app.sold.cameras import CAMERA_BODIES, camera_by_id
        from app.sold.refresh import refresh_sold_evidence

        product = payload.get("product")
        if product:
            body = camera_by_id(str(product))
            bodies = [body] if body else []
        else:
            limit = max(1, min(int(payload.get("limit") or 12), 12))
            bodies = list(CAMERA_BODIES)[:limit]
        markets = payload.get("markets") or ("GB",)
        if isinstance(markets, str):
            markets = tuple(part.strip().upper() for part in markets.split(",") if part.strip()) or ("GB",)
        force = bool(payload.get("force"))
        return await refresh_sold_evidence(
            session,
            bodies=bodies,
            force=force,
            markets=tuple(markets),
            revalidate=bool(payload.get("revalidate", True)),
        )
    if name == "deletion-retry":
        from app.privacy.ebay_processor import retry_failed_deletions

        retried = retry_failed_deletions(session)
        return {"retried": retried}
    if name == "self-audit":
        from app.audit.self_audit import run_self_audit

        audit = run_self_audit(session)
        return {"warnings": len(audit.warnings or [])}
    if name == "sold-ingest":
        from app.sold.ebay_owner_oauth import ingest_owner_orders

        return await ingest_owner_orders(session, limit=int(payload.get("limit") or 100))
    raise ValueError(f"unknown pipeline job {name}")


def beat_worker_process(worker_id: str, *, factory: sessionmaker[Session] | None = None) -> None:
    """One process-liveness beat on its own short-lived session.

    Must not use the job session. A long revalue/scan transaction must not
    block or be interleaved with worker liveness writes.
    """
    from app.core.runtime import process_runtime_snapshot
    from app.db.session import get_session_factory
    from app.jobs.scheduler import local_scheduler_snapshot

    session_factory = factory or get_session_factory()
    session = session_factory()
    try:
        beat_worker(
            session,
            worker_id,
            hostname=os.uname().nodename,
            pid=os.getpid(),
            details={"scheduler": local_scheduler_snapshot(), "runtime": process_runtime_snapshot()},
        )
        session.commit()
    except Exception:
        logger.exception("worker_process_heartbeat_failed", worker_id=worker_id)
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        session.close()


def start_process_heartbeat(
    worker_id: str,
    *,
    interval_seconds: float = WORKER_HEARTBEAT_SECONDS,
    factory: sessionmaker[Session] | None = None,
    stop: threading.Event | None = None,
) -> threading.Event:
    """Beat pipeline_workers on a daemon thread for the life of this process.

    A thread is required because scan/revalue still contain long synchronous
    SQLAlchemy/CPU sections inside ``execute_job``. An asyncio task would stall
    for the same reason the live scan lost worker_connected after 30s.
    """
    halt = stop or threading.Event()

    def _loop() -> None:
        beat_worker_process(worker_id, factory=factory)
        while not halt.wait(interval_seconds):
            beat_worker_process(worker_id, factory=factory)

    thread = threading.Thread(target=_loop, name="arie-worker-heartbeat", daemon=True)
    thread.start()
    logger.info("worker_process_heartbeat_started", worker_id=worker_id, interval_seconds=interval_seconds)
    return halt


async def process_once(session: Session, worker_id: str) -> PipelineJob | None:
    job = claim_next(session, worker_id)
    if job is None:
        session.commit()
        return None
    session.commit()
    try:
        heartbeat(session, job)
        session.commit()
        result = await execute_job(session, job)
        session.commit()
        job = session.get(PipelineJob, job.id)
        finish(session, job, ok=True, details=result if isinstance(result, dict) else {})
        session.commit()
        logger.info("pipeline_job_done", name=job.name if job else None, job_id=str(job.id) if job else None)
        return job
    except Exception as exc:
        session.rollback()
        job = session.get(PipelineJob, job.id)
        finish(session, job, ok=False, error=str(exc))
        session.commit()
        logger.exception("pipeline_job_failed", job_id=str(job.id) if job else None)
        return job


async def run_forever(*, poll_seconds: float = 1.0) -> None:
    from app.db.migrate import run_startup_migrations
    from app.db.session import get_session_factory
    from app.jobs.scheduler import start_scheduler, stop_scheduler

    configure_logging()
    try:
        run_startup_migrations()
    except Exception:
        logger.exception("worker_migrations_failed")
    worker_id = os.environ.get("ARIE_WORKER_ID") or new_worker_id()
    logger.info("pipeline_worker_start", worker_id=worker_id)
    factory = get_session_factory()
    start_scheduler()
    halt = start_process_heartbeat(worker_id, factory=factory)
    try:
        while not _STOP:
            session = factory()
            try:
                await process_once(session, worker_id)
            except Exception:
                logger.exception("pipeline_worker_loop_failed")
                try:
                    session.rollback()
                except Exception:
                    pass
            finally:
                session.close()
            await asyncio.sleep(poll_seconds)
    finally:
        stop_scheduler()
        halt.set()
        logger.info("pipeline_worker_stop", worker_id=worker_id)


def main() -> None:
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
