"""Daily self-audit of sources, stale rules, and worker health."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exits.fees import FEE_SCHEDULE
from app.jobs.scheduler import scheduler_status
from app.models.orm import SelfAudit, Source


def run_self_audit(session: Session) -> SelfAudit:
    now = datetime.now(timezone.utc)
    sources = session.scalars(select(Source)).all()
    warnings: list[str] = []
    health = {}
    for src in sources:
        health[src.id] = {"status": src.status, "error": src.last_error}
        if src.enabled and str(src.status).startswith("BLOCKED"):
            warnings.append(f"{src.id} is {src.status}")
        if src.status == "LIVE" and getattr(src, "commercial_quality", "UNKNOWN") == "LOW":
            warnings.append(f"{src.id} is LIVE but LOW commercial quality")
    stale = []
    for rule in FEE_SCHEDULE:
        age = (now.date() - rule.last_verified).days
        if age > 180:
            stale.append(f"{rule.channel} fee last verified {rule.last_verified}")
            warnings.append(stale[-1])
    sched = scheduler_status()
    if not sched.get("scheduler_running"):
        warnings.append("Worker scheduler is not running.")
    if sched.get("web_scheduler_running"):
        warnings.append("Web process is running APScheduler; background work must not live in web.")
    audit = SelfAudit(ran_at=now, warnings=warnings, source_health=health, stale_rules=stale)
    session.add(audit)
    session.flush()
    return audit
