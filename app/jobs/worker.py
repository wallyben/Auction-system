"""Dedicated pipeline worker. Never run inside the web process.

    python -m app.jobs.worker
"""

from __future__ import annotations

import asyncio
import os
import signal
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import configure_logging, get_logger
from app.jobs.queue import beat_worker, claim_next, finish, heartbeat, new_worker_id
from app.models.orm import PipelineJob

logger = get_logger("arie.jobs.worker")

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
    raise ValueError(f"unknown pipeline job {name}")


async def process_once(session: Session, worker_id: str) -> PipelineJob | None:
    beat_worker(session, worker_id, pid=os.getpid())
    session.commit()
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

    configure_logging()
    try:
        run_startup_migrations()
    except Exception:
        logger.exception("worker_migrations_failed")
    worker_id = os.environ.get("ARIE_WORKER_ID") or new_worker_id()
    logger.info("pipeline_worker_start", worker_id=worker_id)
    factory = get_session_factory()
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
    logger.info("pipeline_worker_stop", worker_id=worker_id)


def main() -> None:
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
