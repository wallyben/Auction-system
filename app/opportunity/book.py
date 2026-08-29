"""Current valuation book generation. Stale algorithms are not commercial."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import BookGeneration, Opportunity
from app.valuation.version import VALUATION_ALGORITHM_VERSION

STATUS_BUILDING = "building"
STATUS_CURRENT = "current"
STATUS_FAILED = "failed"
STATUS_SUPERSEDED = "superseded"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def current_generation(session: Session) -> BookGeneration | None:
    return session.scalars(
        select(BookGeneration)
        .where(BookGeneration.status == STATUS_CURRENT)
        .order_by(BookGeneration.finished_at.desc())
        .limit(1)
    ).first()


def start_generation(session: Session, *, listings_total: int, details: dict[str, Any] | None = None) -> BookGeneration:
    stuck = session.scalars(select(BookGeneration).where(BookGeneration.status == STATUS_BUILDING)).all()
    for row in stuck:
        fail_generation(session, row, "superseded_by_new_run")
    row = BookGeneration(
        algorithm_version=VALUATION_ALGORITHM_VERSION,
        status=STATUS_BUILDING,
        started_at=_now(),
        listings_total=listings_total,
        listings_done=0,
        details=details or {},
    )
    session.add(row)
    session.flush()
    return row


def fail_generation(session: Session, generation: BookGeneration, error: str) -> None:
    generation.status = STATUS_FAILED
    generation.finished_at = _now()
    generation.error = error[:2000]
    session.flush()


def promote_generation(session: Session, generation: BookGeneration) -> None:
    """Only a successful complete run becomes current. Partial runs stay building/failed."""
    previous = session.scalars(select(BookGeneration).where(BookGeneration.status == STATUS_CURRENT)).all()
    for row in previous:
        if row.id != generation.id:
            row.status = STATUS_SUPERSEDED
            row.finished_at = row.finished_at or _now()
    generation.status = STATUS_CURRENT
    generation.finished_at = _now()
    generation.algorithm_version = VALUATION_ALGORITHM_VERSION
    generation.listings_done = generation.listings_done or generation.listings_total
    session.flush()


def is_current_opportunity(opp: Opportunity, generation: BookGeneration | None) -> bool:
    if (opp.algorithm_version or "") != VALUATION_ALGORITHM_VERSION:
        return False
    if generation is None:
        return True
    run_id = getattr(opp, "valuation_run_id", None)
    if run_id is None:
        return False
    return str(run_id) == str(generation.id)


def current_opportunities(session: Session, *, limit: int = 400) -> list[Opportunity]:
    generation = current_generation(session)
    rows = list(session.scalars(select(Opportunity).limit(2000)).all())
    current = [row for row in rows if is_current_opportunity(row, generation)]
    return current[:limit]


def stamp_opportunity(opp: Opportunity, generation: BookGeneration | None) -> None:
    opp.algorithm_version = VALUATION_ALGORITHM_VERSION
    if generation is not None:
        opp.valuation_run_id = generation.id


def parse_run_id(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return None
