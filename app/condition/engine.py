"""Condition normalisation from seller language."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from app.models.enums import ConditionGrade

KEYWORD_MAP: list[tuple[re.Pattern[str], ConditionGrade, Decimal]] = [
    (re.compile(r"\b(for parts|spares|broken|not working|faulty|dead)\b", re.I), ConditionGrade.FOR_PARTS, Decimal("0.9")),
    (re.compile(r"\b(new sealed|brand new|bnib|factory sealed)\b", re.I), ConditionGrade.NEW, Decimal("0.9")),
    (re.compile(r"\b(open box|opened.?never used)\b", re.I), ConditionGrade.OPEN_BOX, Decimal("0.8")),
    (re.compile(r"\b(mint|like new|excellent|pristine|near mint)\b", re.I), ConditionGrade.EXCELLENT, Decimal("0.75")),
    (re.compile(r"\b(very good|lightly used|barely used)\b", re.I), ConditionGrade.VERY_GOOD, Decimal("0.7")),
    (re.compile(r"\b(good(?: condition)?|used|pre-owned|second.?hand)\b", re.I), ConditionGrade.GOOD, Decimal("0.55")),
    (re.compile(r"\b(fair|worn|scratched|heavy use)\b", re.I), ConditionGrade.FAIR, Decimal("0.7")),
    (re.compile(r"\b(poor|damaged|cracked|dented)\b", re.I), ConditionGrade.POOR, Decimal("0.75")),
]

REFURB = {
    ConditionGrade.NEW: (Decimal("0"), Decimal("0")),
    ConditionGrade.OPEN_BOX: (Decimal("5"), Decimal("15")),
    ConditionGrade.EXCELLENT: (Decimal("8"), Decimal("20")),
    ConditionGrade.VERY_GOOD: (Decimal("15"), Decimal("35")),
    ConditionGrade.GOOD: (Decimal("25"), Decimal("60")),
    ConditionGrade.FAIR: (Decimal("40"), Decimal("120")),
    ConditionGrade.POOR: (Decimal("80"), Decimal("220")),
    ConditionGrade.FOR_PARTS: (Decimal("0"), Decimal("0")),
    ConditionGrade.UNKNOWN: (Decimal("20"), Decimal("80")),
}

GRADE_MULTIPLIER = {
    ConditionGrade.NEW: Decimal("1.00"),
    ConditionGrade.OPEN_BOX: Decimal("0.90"),
    ConditionGrade.EXCELLENT: Decimal("0.88"),
    ConditionGrade.VERY_GOOD: Decimal("0.80"),
    ConditionGrade.GOOD: Decimal("0.70"),
    ConditionGrade.FAIR: Decimal("0.55"),
    ConditionGrade.POOR: Decimal("0.35"),
    ConditionGrade.FOR_PARTS: Decimal("0.15"),
    ConditionGrade.UNKNOWN: Decimal("0.65"),
}


@dataclass(slots=True)
class ConditionAssessment:
    grade: ConditionGrade
    confidence: Decimal
    refurb_low_eur: Decimal
    refurb_high_eur: Decimal
    price_multiplier: Decimal
    notes: str


def assess_condition(raw: str | None, description: str = "") -> ConditionAssessment:
    blob = f"{raw or ''}\n{description}"
    for pattern, grade, confidence in KEYWORD_MAP:
        if pattern.search(blob):
            low, high = REFURB[grade]
            return ConditionAssessment(
                grade=grade,
                confidence=confidence,
                refurb_low_eur=low,
                refurb_high_eur=high,
                price_multiplier=GRADE_MULTIPLIER[grade],
                notes=f"Matched seller language to {grade.value}.",
            )
    low, high = REFURB[ConditionGrade.UNKNOWN]
    return ConditionAssessment(
        grade=ConditionGrade.UNKNOWN,
        confidence=Decimal("0.25"),
        refurb_low_eur=low,
        refurb_high_eur=high,
        price_multiplier=GRADE_MULTIPLIER[ConditionGrade.UNKNOWN],
        notes="No reliable condition language. Treated as unknown, not 'used'.",
    )
