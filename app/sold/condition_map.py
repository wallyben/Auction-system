"""Map provider / marketplace conditions into ARIE sold grades.

ARIE sold grades: NEW, LIKE_NEW, EXCELLENT, GOOD, FAIR, POOR, PARTS.
PARTS must not mix into working-camera valuation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.enums import ConditionGrade

SOLD_NEW = "NEW"
SOLD_LIKE_NEW = "LIKE_NEW"
SOLD_EXCELLENT = "EXCELLENT"
SOLD_GOOD = "GOOD"
SOLD_FAIR = "FAIR"
SOLD_POOR = "POOR"
SOLD_PARTS = "PARTS"

WORKING_GRADES = {SOLD_NEW, SOLD_LIKE_NEW, SOLD_EXCELLENT, SOLD_GOOD, SOLD_FAIR}
PARTS_GRADES = {SOLD_PARTS, SOLD_POOR}

# eBay conditionId → ARIE sold grade.
CONDITION_ID_MAP: dict[str, str] = {
    "1000": SOLD_NEW,
    "1500": SOLD_LIKE_NEW,
    "1750": SOLD_LIKE_NEW,
    "2000": SOLD_EXCELLENT,
    "2010": SOLD_EXCELLENT,
    "2020": SOLD_EXCELLENT,
    "2030": SOLD_GOOD,
    "2500": SOLD_EXCELLENT,
    "2750": SOLD_EXCELLENT,
    "3000": SOLD_GOOD,
    "4000": SOLD_EXCELLENT,
    "5000": SOLD_GOOD,
    "6000": SOLD_FAIR,
    "7000": SOLD_PARTS,
}

NAME_MAP: dict[str, str] = {
    "new": SOLD_NEW,
    "brand new": SOLD_NEW,
    "new with tags": SOLD_NEW,
    "new (other)": SOLD_LIKE_NEW,
    "new other": SOLD_LIKE_NEW,
    "open box": SOLD_LIKE_NEW,
    "like new": SOLD_LIKE_NEW,
    "certified refurbished": SOLD_EXCELLENT,
    "excellent - refurbished": SOLD_EXCELLENT,
    "excellent refurbished": SOLD_EXCELLENT,
    "excellent": SOLD_EXCELLENT,
    "very good - refurbished": SOLD_EXCELLENT,
    "very good refurbished": SOLD_EXCELLENT,
    "very good": SOLD_EXCELLENT,
    "seller refurbished": SOLD_GOOD,
    "good - refurbished": SOLD_GOOD,
    "good refurbished": SOLD_GOOD,
    "pre-owned": SOLD_GOOD,
    "used": SOLD_GOOD,
    "good": SOLD_GOOD,
    "acceptable": SOLD_FAIR,
    "fair": SOLD_FAIR,
    "for parts or not working": SOLD_PARTS,
    "for parts": SOLD_PARTS,
    "gebraucht": SOLD_GOOD,
    "wie neu": SOLD_LIKE_NEW,
    "occasion": SOLD_GOOD,
    "neuf": SOLD_NEW,
    "neu": SOLD_NEW,
    "nuovo": SOLD_NEW,
    "usato": SOLD_GOOD,
    "usado": SOLD_GOOD,
}

_PARTS_TEXT = re.compile(
    r"\b(for parts|spares or repair|not working|doesn't work|does not work|"
    r"faulty|broken shutter|no power|pour pièces|zur reparatur)\b",
    re.I,
)

TO_CONDITION_GRADE = {
    SOLD_NEW: ConditionGrade.NEW,
    SOLD_LIKE_NEW: ConditionGrade.OPEN_BOX,
    SOLD_EXCELLENT: ConditionGrade.EXCELLENT,
    SOLD_GOOD: ConditionGrade.GOOD,
    SOLD_FAIR: ConditionGrade.FAIR,
    SOLD_POOR: ConditionGrade.POOR,
    SOLD_PARTS: ConditionGrade.FOR_PARTS,
}

CONDITION_BUCKET = {
    SOLD_NEW: "new",
    SOLD_LIKE_NEW: "new",
    SOLD_EXCELLENT: "used",
    SOLD_GOOD: "used",
    SOLD_FAIR: "used",
    SOLD_POOR: "parts",
    SOLD_PARTS: "parts",
}


@dataclass(slots=True, frozen=True)
class SoldCondition:
    raw: str
    grade: str
    bucket: str
    working: bool
    condition_id: str | None


def map_sold_condition(
    raw: str | None,
    *,
    condition_id: str | int | None = None,
    title: str = "",
) -> SoldCondition:
    cid = str(condition_id).strip() if condition_id not in (None, "") else None
    blob = f"{raw or ''} {title}"
    if cid == "7000" or _PARTS_TEXT.search(blob):
        return SoldCondition(raw or "", SOLD_PARTS, "parts", False, cid)
    if cid and cid in CONDITION_ID_MAP:
        grade = CONDITION_ID_MAP[cid]
        return SoldCondition(raw or "", grade, CONDITION_BUCKET[grade], grade in WORKING_GRADES, cid)
    name = re.sub(r"\s+", " ", (raw or "").strip().lower())
    name = name.replace("–", "-").replace("—", "-")
    if name in NAME_MAP:
        grade = NAME_MAP[name]
        return SoldCondition(raw or "", grade, CONDITION_BUCKET[grade], grade in WORKING_GRADES, cid)
    return SoldCondition(raw or "", SOLD_GOOD, "used", True, cid)


def grades_compatible(subject: str, evidence: str) -> bool:
    """Working vs parts is never compatible. Adjacent working grades are."""
    sub = (subject or SOLD_GOOD).upper()
    ev = (evidence or SOLD_GOOD).upper()
    if sub in PARTS_GRADES or ev in PARTS_GRADES:
        return sub in PARTS_GRADES and ev in PARTS_GRADES
    return True
