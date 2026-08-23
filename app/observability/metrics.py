"""Structured counters persisted with a run id."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.orm import MetricEvent


def record_metric(session: Session, name: str, value: Decimal | int = 1, *, run_id: str | None = None, **labels: object) -> None:
    session.add(
        MetricEvent(
            name=name,
            value=Decimal(str(value)),
            run_id=run_id,
            labels={k: str(v) for k, v in labels.items()},
        )
    )
