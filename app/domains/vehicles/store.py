"""Persist commercial-van cases. No-ops when DATABASE_URL is unset."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.domains.vehicles.enums import CandidateState
from app.domains.vehicles.evaluate import Evaluation
from app.domains.vehicles.orm import CvEvaluationRow, CvOwnerEvidenceRow, CvSourceStateRow


def persist_evaluation(evaluation: Evaluation, *, freeze_shadow: bool = False, session: Session | None = None) -> None:
    own = session is None
    db = session or _open()
    if db is None:
        return
    try:
        row = CvEvaluationRow(
            evaluation_id=uuid.uuid4().hex[:32],
            listing_key=evaluation.listing_key,
            evaluated_at=evaluation.evaluated_at or datetime.now(timezone.utc),
            state=evaluation.state.value,
            shadow=freeze_shadow,
            payload=evaluation.to_dict(),
        )
        db.add(row)
        if own:
            db.commit()
    except Exception:
        if own:
            db.rollback()
        raise
    finally:
        if own:
            db.close()


def load_evaluations(name: str, session: Session | None = None) -> list[dict[str, object]]:
    own = session is None
    db = session or _open()
    if db is None:
        return []
    try:
        rows = list(db.query(CvEvaluationRow).order_by(CvEvaluationRow.evaluated_at.desc()).limit(200).all())
    finally:
        if own and db is not None:
            db.close()
    latest: dict[str, CvEvaluationRow] = {}
    for row in rows:
        latest.setdefault(row.listing_key, row)
    wanted = _wanted(name)
    public: list[dict[str, object]] = []
    for row in latest.values():
        payload = dict(row.payload)
        if wanted is not None and payload.get("state") != wanted:
            continue
        public.append(payload)
    return public


def record_source_state(
    session: Session,
    *,
    source_id: str,
    status: str,
    parser_version: str,
    last_success_at: datetime | None,
    last_error: str,
    payload: dict,
) -> None:
    existing = session.get(CvSourceStateRow, source_id)
    if existing is None:
        session.add(
            CvSourceStateRow(
                source_id=source_id,
                status=status,
                parser_version=parser_version,
                last_success_at=last_success_at,
                last_error=last_error,
                payload=payload,
            )
        )
        return
    existing.status = status
    existing.parser_version = parser_version
    existing.last_success_at = last_success_at
    existing.last_error = last_error
    existing.payload = payload


def record_owner_evidence(session: Session, *, vehicle_key: str, kind: str, payload: dict) -> str:
    evidence_id = uuid.uuid4().hex[:32]
    session.add(
        CvOwnerEvidenceRow(
            evidence_id=evidence_id,
            vehicle_key=vehicle_key or "unassigned",
            kind=kind,
            created_at=datetime.now(timezone.utc),
            payload=payload,
        )
    )
    return evidence_id


def _open() -> Session | None:
    if not os.environ.get("DATABASE_URL", "").strip():
        return None
    from app.db.session import get_session_factory

    return get_session_factory()()


def _wanted(name: str) -> str | None:
    if name == "manual":
        return CandidateState.MANUAL_EVIDENCE_REQUIRED.value
    if name == "price":
        return CandidateState.PRICE_TOO_HIGH.value
    if name == "rejected":
        return CandidateState.REJECT.value
    if name == "insufficient":
        return CandidateState.INSUFFICIENT_DATA.value
    if name == "all":
        return None
    return CandidateState.BUY_CANDIDATE.value
