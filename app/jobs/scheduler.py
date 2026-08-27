"""Background scheduler for continuous scanning."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_session_factory
from app.pipeline.service import run_scan

logger = get_logger("arie.jobs")
_scheduler: AsyncIOScheduler | None = None
_running = False


def scheduler_status() -> dict[str, object]:
    jobs = []
    if _scheduler is not None:
        jobs = [
            {
                "id": job.id,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in _scheduler.get_jobs()
        ]
    return {"scheduler_running": bool(_scheduler and _scheduler.running), "jobs": jobs}


async def _scheduled_scan() -> None:
    global _running
    if _running:
        logger.info("scan_skipped_already_running")
        return
    _running = True
    session = get_session_factory()()
    try:
        await run_scan(session, trigger="scheduler", limit=8)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("scheduled_scan_failed")
    finally:
        session.close()
        _running = False


async def _scheduled_deletion_retry() -> None:
    from app.privacy.ebay_processor import retry_failed_deletions

    session = get_session_factory()()
    try:
        retry_failed_deletions(session)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("ebay_deletion_retry_failed")
    finally:
        session.close()


async def _scheduled_audit() -> None:
    from app.audit.self_audit import run_self_audit

    session = get_session_factory()()
    try:
        run_self_audit(session)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("self_audit_failed")
    finally:
        session.close()


async def _scheduled_sold_ingest() -> None:
    from app.sold.ebay_owner_oauth import ingest_owner_orders

    session = get_session_factory()()
    try:
        result = await ingest_owner_orders(session, limit=100)
        session.commit()
        logger.info(
            "scheduled_sold_ingest",
            ok=result.get("ok"),
            imported=result.get("imported"),
            error=result.get("error"),
        )
    except Exception:
        session.rollback()
        logger.exception("scheduled_sold_ingest_failed")
    finally:
        session.close()


async def _scheduled_revalue() -> None:
    from app.pipeline.service import revalue_all_active
    from app.valuation.version import VALUATION_ALGORITHM_VERSION

    session = get_session_factory()()
    try:
        result = await revalue_all_active(session, reason=f"scheduled:{VALUATION_ALGORITHM_VERSION}")
        session.commit()
        logger.info("scheduled_revalue", **{k: result.get(k) for k in ("revalued", "algorithm_version", "ok")})
    except Exception:
        session.rollback()
        logger.exception("scheduled_revalue_failed")
    finally:
        session.close()


def start_scheduler() -> None:
    global _scheduler
    import sys
    if "pytest" in sys.modules:
        logger.info("scheduler_skipped_under_pytest")
        return
    if not settings.scan_enabled:
        logger.info("scheduler_disabled_by_config")
        return
    _scheduler = AsyncIOScheduler()
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
        _scheduled_revalue,
        CronTrigger(hour=7, minute=40),
        id="revalue-all-active",
        replace_existing=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info("scheduler_started", minutes=settings.fast_marketplace_minutes)
