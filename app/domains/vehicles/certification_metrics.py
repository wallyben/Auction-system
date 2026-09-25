"""Shadow certification measures. A zero sample is not a pass."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Metric:
    name: str
    threshold: str
    measured: str | None
    sample_size: int
    passed: bool | None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "threshold": self.threshold,
            "measured": self.measured,
            "sample_size": self.sample_size,
            "passed": self.passed,
        }


THRESHOLDS = (
    Metric("identity_accuracy", ">= 0.95 where VIN or registration was later confirmed", None, 0, None),
    Metric("commercial_classification_precision", "N1 goods precision >= 0.95 on confirmed homologation", None, 0, None),
    Metric("tax_provenance_correctness", "no unknown check treated as a pass; tax state matches later evidence", None, 0, None),
    Metric("market_valuation_error", "median absolute percentage error of conservative value <= 0.12", None, 0, None),
    Metric("quick_sale_calibration", "quick-sale at or below later observed resale in >= 80% of realised cases", None, 0, None),
    Metric("candidate_precision", "shadow candidates that remain defensible after outcome >= 0.90", None, 0, None),
    Metric("false_positive_rate", "false-positive shadow candidates <= 0.05", None, 0, None),
    Metric("data_freshness", "cohort market observations median age <= 14 days", None, 0, None),
    Metric("source_reliability", "live source success over the last 30 attempts >= 0.90", None, 0, None),
    Metric("max_bid_calibration", "max bid does not exceed a later observed all-in loss threshold", None, 0, None),
)

MINIMUM_HISTORICAL_CASES = 30


def certification_posture(*, historical_cases: int, live_shadow_cases: int) -> str:
    if historical_cases <= 0 and live_shadow_cases <= 0:
        return "NOT_STARTED"
    return "IN_PROGRESS"


def score_certification(*, historical_cases: int, live_shadow_cases: int) -> dict[str, object]:
    posture = certification_posture(historical_cases=historical_cases, live_shadow_cases=live_shadow_cases)
    return {
        "posture": posture,
        "passed": False,
        "minimum_historical_cases": MINIMUM_HISTORICAL_CASES,
        "historical_cases": historical_cases,
        "live_shadow_cases": live_shadow_cases,
        "metrics": [metric.to_dict() for metric in THRESHOLDS],
        "note": (
            "Thresholds are not relaxed to create a pass. "
            f"A result requires at least {MINIMUM_HISTORICAL_CASES} pre-registered historical cases "
            "and a live shadow set. Zero observations are unmeasured, not successful."
        ),
    }


def median_absolute_percentage_error(pairs: list[tuple[Decimal, Decimal]]) -> Decimal | None:
    """pairs are (predicted, realised). Empty input returns None, not zero error."""

    errors: list[Decimal] = []
    for predicted, realised in pairs:
        if realised == 0:
            continue
        errors.append(abs(predicted - realised) / abs(realised))
    if not errors:
        return None
    ordered = sorted(errors)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal("2")
