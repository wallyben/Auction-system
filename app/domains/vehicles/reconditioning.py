"""Repair reserves. Unknown mechanical condition is not a zero cost."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.money import ZERO, money
from app.domains.vehicles.enums import EvidencePosture
from app.domains.vehicles.evidence import MoneyLine
from app.domains.vehicles.policy import UNKNOWN_MECHANICAL_DOWNSIDE_EUR, UNKNOWN_MECHANICAL_EXPECTED_EUR

INSPECTED_CONTINGENCY_EXPECTED_EUR = Decimal("150")
INSPECTED_CONTINGENCY_DOWNSIDE_EUR = Decimal("400")

# Expected and downside EUR for declared issues. These are configured Irish
# reserves, not quotes. They are labelled ESTIMATED.
_ISSUE_COSTS: tuple[tuple[str, Decimal, Decimal], ...] = (
    ("service", Decimal("350"), Decimal("700")),
    ("timing", Decimal("700"), Decimal("1400")),
    ("tyres", Decimal("400"), Decimal("800")),
    ("brakes", Decimal("350"), Decimal("700")),
    ("body", Decimal("600"), Decimal("1800")),
    ("paint", Decimal("450"), Decimal("1200")),
    ("windscreen", Decimal("300"), Decimal("600")),
    ("lights", Decimal("150"), Decimal("400")),
    ("interior", Decimal("200"), Decimal("600")),
    ("valet", Decimal("80"), Decimal("150")),
    ("key", Decimal("250"), Decimal("450")),
    ("battery", Decimal("150"), Decimal("350")),
    ("clutch", Decimal("700"), Decimal("1400")),
    ("dmf", Decimal("900"), Decimal("1600")),
    ("dpf", Decimal("800"), Decimal("1800")),
    ("adblue", Decimal("400"), Decimal("1200")),
    ("suspension", Decimal("400"), Decimal("900")),
    ("nct", Decimal("300"), Decimal("900")),
    ("mot", Decimal("300"), Decimal("900")),
    ("corrosion", Decimal("500"), Decimal("2000")),
    ("accident", Decimal("1500"), Decimal("4000")),
    ("warning", Decimal("400"), Decimal("1500")),
)


@dataclass(frozen=True, slots=True)
class ReconditioningResult:
    expected_eur: Decimal
    downside_eur: Decimal
    posture: EvidencePosture
    mechanical_unknown: bool
    lines: tuple[MoneyLine, ...]
    notes: tuple[str, ...]


def _match(fault: str) -> tuple[str, Decimal, Decimal] | None:
    text = fault.lower()
    for key, expected, downside in _ISSUE_COSTS:
        if key in text:
            return key, expected, downside
    return None


def estimate_reconditioning(
    *,
    declared_faults: tuple[str, ...],
    keys: int | None,
    mechanical_inspected: bool,
) -> ReconditioningResult:
    lines: list[MoneyLine] = []
    expected = ZERO
    downside = ZERO
    notes: list[str] = []
    for fault in declared_faults:
        matched = _match(fault)
        if matched is None:
            expected += Decimal("250")
            downside += Decimal("800")
            lines.append(MoneyLine("unclassified_fault", Decimal("250"), EvidencePosture.ESTIMATED, "seller", fault))
            continue
        key, exp, down = matched
        expected += exp
        downside += down
        lines.append(MoneyLine(key, exp, EvidencePosture.ESTIMATED, "configured_reserve", fault))
    if keys is not None and keys < 2:
        expected += Decimal("250")
        downside += Decimal("450")
        lines.append(MoneyLine("missing_key", Decimal("250"), EvidencePosture.ESTIMATED, "listing", "Fewer than two keys."))
    mechanical_unknown = not mechanical_inspected
    if mechanical_unknown:
        expected += UNKNOWN_MECHANICAL_EXPECTED_EUR
        downside += UNKNOWN_MECHANICAL_DOWNSIDE_EUR
        lines.append(
            MoneyLine(
                "unknown_mechanical",
                UNKNOWN_MECHANICAL_EXPECTED_EUR,
                EvidencePosture.ESTIMATED,
                "policy",
                "No inspection. Mechanical condition is not costed at zero.",
            )
        )
        notes.append("Mechanical condition was not inspected. A contingency is reserved and the condition gate stays closed.")
    else:
        expected += INSPECTED_CONTINGENCY_EXPECTED_EUR
        downside += INSPECTED_CONTINGENCY_DOWNSIDE_EUR
        lines.append(
            MoneyLine(
                "inspected_contingency",
                INSPECTED_CONTINGENCY_EXPECTED_EUR,
                EvidencePosture.ESTIMATED,
                "policy",
                "Inspection does not remove a residual contingency.",
            )
        )
    return ReconditioningResult(
        expected_eur=money(expected),
        downside_eur=money(downside),
        posture=EvidencePosture.ESTIMATED,
        mechanical_unknown=mechanical_unknown,
        lines=tuple(lines),
        notes=tuple(notes),
    )
