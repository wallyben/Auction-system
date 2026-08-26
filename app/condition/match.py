"""Condition-match scoring between a candidate and a realised comp."""

from __future__ import annotations

from decimal import Decimal

from app.condition.engine import assess_condition
from app.models.enums import ConditionGrade

_RANK = {
    ConditionGrade.NEW: 8,
    ConditionGrade.OPEN_BOX: 7,
    ConditionGrade.EXCELLENT: 6,
    ConditionGrade.VERY_GOOD: 5,
    ConditionGrade.GOOD: 4,
    ConditionGrade.FAIR: 3,
    ConditionGrade.POOR: 2,
    ConditionGrade.FOR_PARTS: 0,
    ConditionGrade.UNKNOWN: 4,
}


def condition_match_score(
    subject_raw: str | None,
    comp_raw: str | None,
    *,
    subject_description: str = "",
    comp_description: str = "",
    subject_condition_id: str | None = None,
    comp_condition_id: str | None = None,
) -> Decimal:
    subject = assess_condition(subject_raw, subject_description, condition_id=subject_condition_id)
    comp = assess_condition(comp_raw, comp_description, condition_id=comp_condition_id)
    if subject.grade is ConditionGrade.FOR_PARTS or comp.grade is ConditionGrade.FOR_PARTS:
        if subject.grade is comp.grade:
            return Decimal("0.70")
        return Decimal("0")
    delta = abs(_RANK[subject.grade] - _RANK[comp.grade])
    if delta == 0:
        return Decimal("1.00")
    if delta == 1:
        return Decimal("0.85")
    if delta == 2:
        return Decimal("0.65")
    return Decimal("0.35")
