"""Provenance-bearing evidence. Absence is UNKNOWN, never a clear result."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.domains.vehicles.enums import CheckOutcome, EvidencePosture


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    field: str
    posture: EvidencePosture
    status: str
    confidence: Decimal
    source: str
    interpretation: str
    blocking: bool
    retrieved_at: datetime | None = None
    source_url: str | None = None
    raw_reference: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "field": self.field,
            "posture": self.posture.value,
            "status": self.status,
            "confidence": str(self.confidence),
            "source": self.source,
            "interpretation": self.interpretation,
            "blocking": self.blocking,
            "retrieved_at": self.retrieved_at.isoformat() if self.retrieved_at else None,
            "source_url": self.source_url,
            "raw_reference": self.raw_reference,
        }


@dataclass(frozen=True, slots=True)
class CheckResult:
    """A due-diligence check. NOT_CHECKED means the source was not consulted."""

    name: str
    outcome: CheckOutcome
    posture: EvidencePosture
    source: str
    interpretation: str
    blocking: bool
    retrieved_at: datetime | None = None
    raw_reference: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "outcome": self.outcome.value,
            "posture": self.posture.value,
            "source": self.source,
            "interpretation": self.interpretation,
            "blocking": self.blocking,
            "retrieved_at": self.retrieved_at.isoformat() if self.retrieved_at else None,
            "raw_reference": self.raw_reference,
        }


def not_checked(name: str, interpretation: str, *, blocking: bool = True) -> CheckResult:
    return CheckResult(
        name=name,
        outcome=CheckOutcome.NOT_CHECKED,
        posture=EvidencePosture.UNKNOWN,
        source="",
        interpretation=interpretation,
        blocking=blocking,
    )


@dataclass(frozen=True, slots=True)
class MoneyLine:
    name: str
    amount_eur: Decimal | None
    posture: EvidencePosture
    source: str
    note: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "amount_eur": str(self.amount_eur) if self.amount_eur is not None else None,
            "posture": self.posture.value,
            "source": self.source,
            "note": self.note,
        }


@dataclass(slots=True)
class EvidenceLedger:
    records: list[EvidenceRecord] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)

    def add(self, record: EvidenceRecord) -> None:
        self.records.append(record)

    def add_check(self, check: CheckResult) -> None:
        self.checks.append(check)

    def to_dict(self) -> dict[str, object]:
        return {
            "records": [record.to_dict() for record in self.records],
            "checks": [check.to_dict() for check in self.checks],
        }
