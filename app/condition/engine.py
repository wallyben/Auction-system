"""Condition normalisation from seller language and structured marketplace fields.

The eBay Browse `condition` field is often the structured name "Used". Mapping that
token through the free-text keyword `used` → GOOD @ 0.55 made CONDITION_PASS fail
~99% of legitimate used goods. Structured marketplace condition is mapped first,
at high confidence. The BUY_READY threshold (0.75) is not lowered.
"""

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

# eBay conditionId → (grade, confidence). Structured, not keyword-scraped.
EBAY_CONDITION_ID: dict[str, tuple[ConditionGrade, Decimal]] = {
    "1000": (ConditionGrade.NEW, Decimal("0.92")),
    "1500": (ConditionGrade.OPEN_BOX, Decimal("0.84")),
    "1750": (ConditionGrade.OPEN_BOX, Decimal("0.80")),
    "2000": (ConditionGrade.EXCELLENT, Decimal("0.86")),
    "2010": (ConditionGrade.EXCELLENT, Decimal("0.86")),
    "2020": (ConditionGrade.VERY_GOOD, Decimal("0.84")),
    "2030": (ConditionGrade.GOOD, Decimal("0.82")),
    "2500": (ConditionGrade.VERY_GOOD, Decimal("0.82")),
    "2750": (ConditionGrade.EXCELLENT, Decimal("0.88")),
    "3000": (ConditionGrade.GOOD, Decimal("0.82")),
    "4000": (ConditionGrade.VERY_GOOD, Decimal("0.85")),
    "5000": (ConditionGrade.GOOD, Decimal("0.80")),
    "6000": (ConditionGrade.FAIR, Decimal("0.80")),
    "7000": (ConditionGrade.FOR_PARTS, Decimal("0.92")),
}

EBAY_CONDITION_NAME: dict[str, tuple[ConditionGrade, Decimal]] = {
    "new": (ConditionGrade.NEW, Decimal("0.92")),
    "brand new": (ConditionGrade.NEW, Decimal("0.92")),
    "new with tags": (ConditionGrade.NEW, Decimal("0.90")),
    "new without tags": (ConditionGrade.OPEN_BOX, Decimal("0.84")),
    "new (other)": (ConditionGrade.OPEN_BOX, Decimal("0.82")),
    "new other": (ConditionGrade.OPEN_BOX, Decimal("0.82")),
    "new other (see details)": (ConditionGrade.OPEN_BOX, Decimal("0.82")),
    "open box": (ConditionGrade.OPEN_BOX, Decimal("0.88")),
    "certified refurbished": (ConditionGrade.EXCELLENT, Decimal("0.86")),
    "excellent - refurbished": (ConditionGrade.EXCELLENT, Decimal("0.86")),
    "excellent refurbished": (ConditionGrade.EXCELLENT, Decimal("0.86")),
    "very good - refurbished": (ConditionGrade.VERY_GOOD, Decimal("0.84")),
    "very good refurbished": (ConditionGrade.VERY_GOOD, Decimal("0.84")),
    "good - refurbished": (ConditionGrade.GOOD, Decimal("0.82")),
    "good refurbished": (ConditionGrade.GOOD, Decimal("0.82")),
    "seller refurbished": (ConditionGrade.VERY_GOOD, Decimal("0.82")),
    "like new": (ConditionGrade.EXCELLENT, Decimal("0.88")),
    "used": (ConditionGrade.GOOD, Decimal("0.82")),
    "very good": (ConditionGrade.VERY_GOOD, Decimal("0.85")),
    "good": (ConditionGrade.GOOD, Decimal("0.80")),
    "acceptable": (ConditionGrade.FAIR, Decimal("0.80")),
    "for parts or not working": (ConditionGrade.FOR_PARTS, Decimal("0.92")),
    "gebraucht": (ConditionGrade.GOOD, Decimal("0.82")),
    "wie neu": (ConditionGrade.EXCELLENT, Decimal("0.86")),
    "très bon état": (ConditionGrade.VERY_GOOD, Decimal("0.82")),
    "bon état": (ConditionGrade.GOOD, Decimal("0.80")),
    "ottimo": (ConditionGrade.VERY_GOOD, Decimal("0.82")),
    "usato": (ConditionGrade.GOOD, Decimal("0.82")),
    "usado": (ConditionGrade.GOOD, Decimal("0.82")),
}

_PARTS = re.compile(
    r"\b(for parts|spares or repair|not working|doesn't work|does not work|faulty|dead pixel screen cracked beyond use)\b",
    re.I,
)
_BATTERY = re.compile(r"\bbattery(?: health)?\s*(?:bh)?[:\s]*(\d{2,3})\s*%", re.I)
_SHUTTER = re.compile(r"\bshutter\s*(?:count|actuations)?[:\s]*([0-9]{1,7})", re.I)


@dataclass(slots=True)
class ConditionAssessment:
    grade: ConditionGrade
    confidence: Decimal
    refurb_low_eur: Decimal
    refurb_high_eur: Decimal
    price_multiplier: Decimal
    notes: str


def _finish(grade: ConditionGrade, confidence: Decimal, notes: str) -> ConditionAssessment:
    low, high = REFURB[grade]
    return ConditionAssessment(
        grade=grade,
        confidence=confidence,
        refurb_low_eur=low,
        refurb_high_eur=high,
        price_multiplier=GRADE_MULTIPLIER[grade],
        notes=notes,
    )


def _structured(raw: str | None, condition_id: str | None) -> tuple[ConditionGrade, Decimal, str] | None:
    cid = str(condition_id or "").strip()
    if cid in EBAY_CONDITION_ID:
        grade, conf = EBAY_CONDITION_ID[cid]
        return grade, conf, f"eBay conditionId {cid} → {grade.value}."
    name = re.sub(r"\s+", " ", (raw or "").strip().lower())
    name = name.replace("–", "-").replace("—", "-")
    if name in EBAY_CONDITION_NAME:
        grade, conf = EBAY_CONDITION_NAME[name]
        return grade, conf, f"Structured marketplace condition '{raw}' → {grade.value}."
    return None


def assess_condition(
    raw: str | None,
    description: str = "",
    *,
    condition_id: str | None = None,
    specifics: dict | None = None,
) -> ConditionAssessment:
    blob = f"{raw or ''}\n{description}"
    if specifics:
        blob += "\n" + " ".join(f"{k} {v}" for k, v in specifics.items())

    if _PARTS.search(blob) or (condition_id and str(condition_id) == "7000"):
        return _finish(ConditionGrade.FOR_PARTS, Decimal("0.92"), "Parts / not-working language or conditionId 7000.")

    structured = _structured(raw, condition_id)
    if structured:
        grade, conf, notes = structured
        extras: list[str] = [notes]
        batt = _BATTERY.search(blob)
        if batt:
            pct = int(batt.group(1))
            extras.append(f"battery_health={pct}%")
            if pct < 80 and grade in {ConditionGrade.EXCELLENT, ConditionGrade.VERY_GOOD, ConditionGrade.GOOD}:
                conf = min(conf, Decimal("0.80"))
                extras.append("battery below 80% caps grade confidence.")
        shutter = _SHUTTER.search(blob)
        if shutter:
            extras.append(f"shutter_count={shutter.group(1)}")
        if re.search(r"\b(refurbished|seller refurbished|certified refurbished)\b", blob, re.I):
            extras.append("refurbished flag present.")
        return _finish(grade, conf, " ".join(extras))

    for pattern, grade, confidence in KEYWORD_MAP:
        if pattern.search(blob):
            return _finish(grade, confidence, f"Matched seller language to {grade.value}.")
    return _finish(
        ConditionGrade.UNKNOWN,
        Decimal("0.25"),
        "No reliable condition language. Treated as unknown, not 'used'.",
    )
