"""Candidate board.

In-process rows keep the owner page responsive. When DATABASE_URL is set, the
same evaluations are written to Postgres and reloaded after a web restart.
A cached BUY_CANDIDATE older than the market freshness window is shown as
manual evidence, not as a live candidate. The frozen shadow snapshot is kept.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.domains.vehicles.enums import CandidateState
from app.domains.vehicles.evaluate import Evaluation, rank_candidates
from app.domains.vehicles.policy import MARKET_FRESH_DAYS

_LOCK = threading.Lock()
_ROWS: list[Evaluation] = []
_SHADOW: list[dict[str, object]] = []


def remember(evaluation: Evaluation, *, freeze_shadow: bool = False) -> None:
    with _LOCK:
        _ROWS[:] = [row for row in _ROWS if row.listing_key != evaluation.listing_key]
        _ROWS.append(evaluation)
        if len(_ROWS) > 200:
            del _ROWS[:-200]
        if freeze_shadow:
            frozen = evaluation.to_dict()
            frozen["frozen"] = True
            _SHADOW.append(frozen)
    _try_persist(evaluation, freeze_shadow=freeze_shadow)


def clear() -> None:
    with _LOCK:
        _ROWS.clear()
        _SHADOW.clear()


def shadow_count() -> int:
    with _LOCK:
        return len(_SHADOW)


def shadow_rows() -> list[dict[str, object]]:
    with _LOCK:
        return list(_SHADOW)


def view(name: str) -> list[dict[str, object]]:
    now = datetime.now(timezone.utc)
    with _LOCK:
        has_memory = bool(_ROWS)
        objects = [_downgrade(row, now) for row in _ROWS]
    if has_memory:
        objects = _filter_objects(objects, name)
        return [row.to_dict() for row in rank_candidates(objects)]
    return _load_stored(name)


def _filter_objects(rows: list[Evaluation], name: str) -> list[Evaluation]:
    wanted = _state_for(name)
    if wanted is None:
        return rows
    return [row for row in rows if row.state is wanted]


def _state_for(name: str) -> CandidateState | None:
    if name == "manual":
        return CandidateState.MANUAL_EVIDENCE_REQUIRED
    if name == "price":
        return CandidateState.PRICE_TOO_HIGH
    if name == "rejected":
        return CandidateState.REJECT
    if name == "insufficient":
        return CandidateState.INSUFFICIENT_DATA
    if name == "all":
        return None
    return CandidateState.BUY_CANDIDATE


def _downgrade(evaluation: Evaluation, now: datetime) -> Evaluation:
    if evaluation.state is not CandidateState.BUY_CANDIDATE:
        return evaluation
    evaluated = evaluation.evaluated_at or now
    if evaluated.tzinfo is None:
        evaluated = evaluated.replace(tzinfo=timezone.utc)
    stale_market = not evaluation.valuation.fresh
    stale_clock = now - evaluated > timedelta(days=MARKET_FRESH_DAYS)
    closed = False
    if evaluation.closes_at:
        try:
            closes = datetime.fromisoformat(evaluation.closes_at)
        except ValueError:
            closes = None
        if closes is not None:
            if closes.tzinfo is None:
                closes = closes.replace(tzinfo=timezone.utc)
            closed = now > closes
    if not (stale_market or stale_clock or closed):
        return evaluation
    reason = "Stale cached candidate downgraded. Refresh the bid, fees, and Irish market book."
    if closed:
        reason = "Auction close has passed. The cached candidate is no longer a live bid."
    return replace(
        evaluation,
        state=CandidateState.MANUAL_EVIDENCE_REQUIRED,
        why=f"{evaluation.why} {reason}",
    )


def _try_persist(evaluation: Evaluation, *, freeze_shadow: bool) -> None:
    try:
        from app.domains.vehicles.store import persist_evaluation

        persist_evaluation(evaluation, freeze_shadow=freeze_shadow)
    except Exception:
        return


def _load_stored(name: str) -> list[dict[str, object]]:
    try:
        from app.domains.vehicles.store import load_evaluations

        return load_evaluations(name)
    except Exception:
        return []
