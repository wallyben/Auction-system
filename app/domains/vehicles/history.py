"""Mileage and history checks. An unchecked register is not a clear result."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from app.domains.vehicles.enums import CheckOutcome, EvidencePosture
from app.domains.vehicles.evidence import CheckResult, EvidenceLedger
from app.domains.vehicles.policy import MILEAGE_ROLLBACK_TOLERANCE_KM


@dataclass(frozen=True, slots=True)
class OdometerReading:
    observed_at: datetime
    mileage_km: int
    source: str
    reference: str


@dataclass(frozen=True, slots=True)
class HistoryInput:
    listing_mileage_km: int | None
    readings: tuple[OdometerReading, ...] = ()
    stolen: CheckResult | None = None
    finance: CheckResult | None = None
    write_off: CheckResult | None = None
    declared_faults: tuple[str, ...] = ()
    keys: int | None = None
    service_history_reference: str | None = None


@dataclass(frozen=True, slots=True)
class HistoryAssessment:
    mileage: CheckResult
    stolen: CheckResult
    finance: CheckResult
    write_off: CheckResult
    blocking_failure: bool


def assess_mileage(listing_km: int | None, readings: tuple[OdometerReading, ...]) -> CheckResult:
    ordered = tuple(sorted(readings, key=lambda row: row.observed_at))
    if listing_km is None and not ordered:
        return CheckResult(
            name="mileage",
            outcome=CheckOutcome.NOT_CHECKED,
            posture=EvidencePosture.UNKNOWN,
            source="",
            interpretation="No odometer and no MOT/NCT history. Mileage was not checked.",
            blocking=True,
        )
    for earlier, later in zip(ordered, ordered[1:]):
        if later.mileage_km + MILEAGE_ROLLBACK_TOLERANCE_KM < earlier.mileage_km:
            return CheckResult(
                name="mileage",
                outcome=CheckOutcome.FAIL,
                posture=EvidencePosture.PROVEN,
                source=later.source,
                interpretation=(
                    f"Later reading {later.mileage_km} km is below earlier {earlier.mileage_km} km "
                    f"({earlier.reference} then {later.reference})."
                ),
                blocking=True,
                raw_reference=later.reference,
            )
    if ordered and listing_km is not None and listing_km + MILEAGE_ROLLBACK_TOLERANCE_KM < ordered[-1].mileage_km:
        return CheckResult(
            name="mileage",
            outcome=CheckOutcome.FAIL,
            posture=EvidencePosture.PROVEN,
            source=ordered[-1].source,
            interpretation=(
                f"Listing mileage {listing_km} km is below the latest history reading "
                f"{ordered[-1].mileage_km} km."
            ),
            blocking=True,
            raw_reference=ordered[-1].reference,
        )
    if not ordered:
        return CheckResult(
            name="mileage",
            outcome=CheckOutcome.NOT_CHECKED,
            posture=EvidencePosture.UNKNOWN,
            source="listing",
            interpretation="Listing states a mileage but no MOT/NCT history was supplied to test it.",
            blocking=True,
        )
    return CheckResult(
        name="mileage",
        outcome=CheckOutcome.CLEAR,
        posture=EvidencePosture.PROVEN,
        source=ordered[-1].source,
        interpretation="History readings are non-decreasing and the listing mileage is not below the latest reading.",
        blocking=False,
        raw_reference=ordered[-1].reference,
    )


def _unchecked(name: str, text: str) -> CheckResult:
    return CheckResult(
        name=name,
        outcome=CheckOutcome.NOT_CHECKED,
        posture=EvidencePosture.UNKNOWN,
        source="",
        interpretation=text,
        blocking=True,
    )


def assess_history(data: HistoryInput, ledger: EvidenceLedger) -> HistoryAssessment:
    mileage = assess_mileage(data.listing_mileage_km, data.readings)
    stolen = data.stolen or _unchecked("stolen", "Stolen status was not checked. Absence of a result is not a clear.")
    finance = data.finance or _unchecked(
        "finance",
        "Outstanding finance was not checked. No recorded result does not mean finance-free.",
    )
    write_off = data.write_off or _unchecked("write_off", "Write-off status was not checked.")
    for check in (mileage, stolen, finance, write_off):
        ledger.add_check(check)
    blocking = any(
        check.blocking and check.outcome is not CheckOutcome.CLEAR
        for check in (mileage, stolen, finance, write_off)
    )
    if data.declared_faults:
        ledger.add_check(
            CheckResult(
                name="declared_faults",
                outcome=CheckOutcome.ANOMALY,
                posture=EvidencePosture.ESTIMATED,
                source="seller",
                interpretation="; ".join(data.declared_faults),
                blocking=False,
            )
        )
    return HistoryAssessment(
        mileage=mileage,
        stolen=stolen,
        finance=finance,
        write_off=write_off,
        blocking_failure=blocking,
    )


def clear_check(name: str, source: str, reference: str, interpretation: str, retrieved_at: datetime | None = None) -> CheckResult:
    return CheckResult(
        name=name,
        outcome=CheckOutcome.CLEAR,
        posture=EvidencePosture.PROVEN,
        source=source,
        interpretation=interpretation,
        blocking=False,
        raw_reference=reference,
        retrieved_at=retrieved_at,
    )
