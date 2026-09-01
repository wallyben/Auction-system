"""Background scheduler: enqueue only. Lives in the WORKER process.

The web process must never instantiate APScheduler. Scheduled functions only
insert durable pipeline_jobs; the worker consumer executes them.
"""

from __future__ import annotations

import os
import sys

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.logging import get_logger
from app.core.process import is_web_process, process_role
from app.db.session import get_session_factory
from app.jobs.queue import enqueue, lease_status
from app.valuation.version import VALUATION_ALGORITHM_VERSION

logger = get_logger("arie.jobs")
_scheduler: BackgroundScheduler | None = None

REQUIRED_JOB_IDS = (
    "scan-live-sources",
    "sold-evidence-refresh",
    "revalue-after-evidence",
    "revalue-all-active",
)

SCHEDULER_PIPELINE_JOBS = (
    "ebay-deletion-retry",
    "daily-self-audit",
    "owner-sold-ingest",
)


def local_scheduler_snapshot() -> dict[str, object]:
    jobs: list[dict[str, object]] = []
    running = bool(_scheduler is not None and _scheduler.running)
    if _scheduler is not None:
        jobs = [
            {
                "id": job.id,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in _scheduler.get_jobs()
        ]
    return {
        "running": running,
        "jobs": jobs,
        "owner": "worker" if running and not is_web_process() else ("web" if running else "none"),
    }


def scheduler_status() -> dict[str, object]:
    local = local_scheduler_snapshot()
    role = process_role()
    payload: dict[str, object] = {
        "scheduler_running": bool(local["running"]),
        "web_scheduler_running": bool(role == "web" and local["running"]),
        "scheduler_owner": local["owner"],
        "process_role": role,
        "jobs": list(local["jobs"]),  # type: ignore[arg-type]
    }
    try:
        session = get_session_factory()()
        try:
            payload["pipeline"] = lease_status(session)
        finally:
            session.close()
    except Exception:
        payload["pipeline"] = lease_status(None)
    pipeline = payload.get("pipeline") if isinstance(payload.get("pipeline"), dict) else {}
    worker = (pipeline or {}).get("worker") if isinstance(pipeline, dict) else None
    snap = (worker or {}).get("scheduler") if isinstance(worker, dict) else None
    if not local["running"] and isinstance(snap, dict) and snap.get("running"):
        payload["scheduler_running"] = True
        payload["jobs"] = list(snap.get("jobs") or [])
        payload["scheduler_owner"] = "worker"
    return payload


def _enqueue_or_skip(name: str, trigger: str, payload: dict | None = None) -> dict:
    session = get_session_factory()()
    try:
        job, result = enqueue(session, name, trigger, payload)
        session.commit()
        if not result.get("ok") and result.get("reason") == "busy":
            logger.info("pipeline_enqueue_skipped_busy", name=name, trigger=trigger)
        else:
            logger.info("pipeline_enqueued", name=name, trigger=trigger, job_id=result.get("job_id"))
        return result
    except Exception:
        session.rollback()
        logger.exception("pipeline_enqueue_failed", name=name)
        return {"ok": False, "reason": "error"}
    finally:
        session.close()


def _scheduled_scan() -> None:
    _enqueue_or_skip("scan", "scheduler", {"limit": 8})


def _scheduled_deletion_retry() -> None:
    _enqueue_or_skip("deletion-retry", "scheduler", {})


def _scheduled_audit() -> None:
    _enqueue_or_skip("self-audit", "scheduler", {})


def _scheduled_sold_ingest() -> None:
    _enqueue_or_skip("sold-ingest", "scheduler", {"limit": 100})


def _scheduled_sold_refresh() -> None:
    _enqueue_or_skip("sold-refresh", "scheduler", {"limit": 12, "markets": "GB"})


def _scheduled_revalue() -> None:
    _enqueue_or_skip("revalue", "scheduler", {"reason": f"scheduled:{VALUATION_ALGORITHM_VERSION}"})


def start_scheduler() -> None:
    """Start APScheduler in the worker process only."""
    global _scheduler
    if is_web_process():
        logger.warning("scheduler_refused_web_process")
        return
    if "pytest" in sys.modules and os.environ.get("ARIE_ALLOW_SCHEDULER") != "1":
        logger.info("scheduler_skipped_under_pytest")
        return
    if not settings.scan_enabled:
        logger.info("scheduler_disabled_by_config")
        return
    if _scheduler is not None and _scheduler.running:
        logger.info("scheduler_already_running")
        return
    stop_scheduler()
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _scheduled_scan,
        IntervalTrigger(minutes=max(settings.fast_marketplace_minutes, 5), jitter=30),
        id="scan-live-sources",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _scheduled_audit,
        CronTrigger(hour=6, minute=15),
        id="daily-self-audit",
        replace_existing=True,
        max_instances=1,
    )
    _scheduler.add_job(
        _scheduled_deletion_retry,
        IntervalTrigger(minutes=15, jitter=20),
        id="ebay-deletion-retry",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _scheduled_sold_ingest,
        IntervalTrigger(hours=3, jitter=120),
        id="owner-sold-ingest",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _scheduled_sold_refresh,
        IntervalTrigger(hours=6, jitter=180),
        id="sold-evidence-refresh",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _scheduled_revalue,
        IntervalTrigger(hours=6, jitter=90),
        id="revalue-after-evidence",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _scheduled_revalue,
        CronTrigger(hour=7, minute=40),
        id="revalue-all-active",
        replace_existing=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info(
        "scheduler_started",
        minutes=settings.fast_marketplace_minutes,
        process_role=process_role(),
        job_count=len(_scheduler.get_jobs()),
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        if _scheduler.running:
            _scheduler.shutdown(wait=False)
    except Exception:
        logger.exception("scheduler_stop_failed")
    _scheduler = None
    logger.info("scheduler_stopped")
