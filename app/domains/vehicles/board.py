"""Process-local candidate board.

This is not durable and it is not shared across web processes. It exists so
the owner page can show evaluations made in this process. The market book
that valuations use is the evidence passed into each evaluation.
"""

from __future__ import annotations

import threading

from app.domains.vehicles.enums import CandidateState
from app.domains.vehicles.evaluate import Evaluation, rank_candidates

_LOCK = threading.Lock()
_ROWS: list[Evaluation] = []


def remember(evaluation: Evaluation) -> None:
    with _LOCK:
        _ROWS.append(evaluation)
        if len(_ROWS) > 50:
            del _ROWS[:-50]


def clear() -> None:
    with _LOCK:
        _ROWS.clear()


def view(name: str) -> list[Evaluation]:
    with _LOCK:
        rows = list(_ROWS)
    if name == "manual":
        rows = [row for row in rows if row.state is CandidateState.MANUAL_EVIDENCE_REQUIRED]
    elif name == "price":
        rows = [row for row in rows if row.state is CandidateState.PRICE_TOO_HIGH]
    elif name == "rejected":
        rows = [row for row in rows if row.state is CandidateState.REJECT]
    elif name == "insufficient":
        rows = [row for row in rows if row.state is CandidateState.INSUFFICIENT_DATA]
    elif name == "all":
        pass
    else:
        rows = [row for row in rows if row.state is CandidateState.BUY_CANDIDATE]
    return rank_candidates(rows)
