"""Tier-1 condition intelligence. Defect language changes grade and repair envelope."""

from __future__ import annotations

import re
from decimal import Decimal

from app.condition.engine import ConditionAssessment, assess_condition
from app.models.enums import ConditionGrade

_CAMERA = [
    (re.compile(r"\bfungus\b", re.I), "fungus", Decimal("180"), Decimal("350"), Decimal("550")),
    (re.compile(r"\bhaze\b", re.I), "haze", Decimal("80"), Decimal("160"), Decimal("280")),
    (re.compile(r"\b(scratch(?:es)? on (?:front|rear) element|element scratch)\b", re.I), "glass_scratch", Decimal("40"), Decimal("90"), Decimal("200")),
    (re.compile(r"\b(dent(?:s)?|ding)\b", re.I), "dent", Decimal("20"), Decimal("45"), Decimal("90")),
    (re.compile(r"\b(mount (?:damage|bent)|bent mount)\b", re.I), "mount", Decimal("60"), Decimal("140"), Decimal("260")),
    (re.compile(r"\b(missing caps|no caps)\b", re.I), "caps", Decimal("10"), Decimal("18"), Decimal("30")),
    (re.compile(r"\bshutter\s*(count|actuations)\s*[:\s]*(\d+)", re.I), "shutter", Decimal("0"), Decimal("0"), Decimal("0")),
    (re.compile(r"\b(af (?:fault|issue)|no autofocus)\b", re.I), "af", Decimal("70"), Decimal("150"), Decimal("280")),
]
_LAPTOP = [
    (re.compile(r"\b(cracked screen|broken screen)\b", re.I), "screen", Decimal("120"), Decimal("220"), Decimal("380")),
    (re.compile(r"\b(battery (?:health|wear|cycle)|battery \d+%)\b", re.I), "battery", Decimal("40"), Decimal("80"), Decimal("140")),
    (re.compile(r"\b(missing charger|no psu|no charger)\b", re.I), "charger", Decimal("25"), Decimal("45"), Decimal("80")),
    (re.compile(r"\b(keyboard (?:damage|fault)|keys missing)\b", re.I), "keyboard", Decimal("40"), Decimal("90"), Decimal("160")),
    (re.compile(r"\b(activation lock|icloud lock|mdm|find my)\b", re.I), "lock", Decimal("0"), Decimal("0"), Decimal("0")),
]
_CONSOLE = [
    (re.compile(r"\b(no controller|missing controller)\b", re.I), "controller", Decimal("40"), Decimal("55"), Decimal("80")),
    (re.compile(r"\b(digital edition|no drive)\b", re.I), "digital", Decimal("0"), Decimal("0"), Decimal("0")),
    (re.compile(r"\b(banned|console ban|hwid)\b", re.I), "ban", Decimal("0"), Decimal("0"), Decimal("0")),
    (re.compile(r"\b(hdmi (?:port )?(?:damage|fault)|no hdmi)\b", re.I), "hdmi", Decimal("40"), Decimal("80"), Decimal("130")),
]
_AUDIO = [
    (re.compile(r"\b(fader (?:damage|scratch|crackly))\b", re.I), "fader", Decimal("30"), Decimal("70"), Decimal("130")),
    (re.compile(r"\b(missing psu|no power supply)\b", re.I), "psu", Decimal("20"), Decimal("40"), Decimal("70")),
    (re.compile(r"\b(channel (?:fault|dead)|one channel)\b", re.I), "channel", Decimal("40"), Decimal("90"), Decimal("180")),
]


def assess_category_condition(raw: str | None, description: str = "", category: str | None = None) -> ConditionAssessment:
    base = assess_condition(raw, description)
    blob = f"{raw or ''}\n{description}"
    table = {
        "cameras": _CAMERA,
        "lenses": _CAMERA,
        "computing": _LAPTOP,
        "consumer_electronics": _LAPTOP,
        "gaming": _CONSOLE,
        "music_dj": _AUDIO,
        "pro_av": _AUDIO,
    }.get(category or "", [])
    low = base.refurb_low_eur
    high = base.refurb_high_eur
    notes = [base.notes]
    repair_required = False
    for pattern, code, a, b, c in table:
        match = pattern.search(blob)
        if not match:
            continue
        repair_required = True
        low += a
        high += c
        notes.append(f"{code}: repair envelope €{a}-€{c}.")
        if code == "lock" or code == "ban":
            return ConditionAssessment(
                grade=ConditionGrade.FOR_PARTS,
                confidence=Decimal("0.85"),
                refurb_low_eur=Decimal("0"),
                refurb_high_eur=Decimal("0"),
                price_multiplier=Decimal("0.10"),
                notes="Activation lock / console ban. Not a retailable unit.",
            )
        if code == "fungus":
            base = ConditionAssessment(
                grade=ConditionGrade.FAIR,
                confidence=Decimal("0.80"),
                refurb_low_eur=low,
                refurb_high_eur=high,
                price_multiplier=Decimal("0.50"),
                notes="; ".join(notes),
            )
    expected = (low + high) / Decimal("2")
    extras = f" repair_required={repair_required} expected_repair€{expected}"
    return ConditionAssessment(
        grade=base.grade,
        confidence=base.confidence if not repair_required else max(base.confidence, Decimal("0.70")),
        refurb_low_eur=low,
        refurb_high_eur=high,
        price_multiplier=base.price_multiplier,
        notes=base.notes + extras + " " + " ".join(notes[1:]),
    )
