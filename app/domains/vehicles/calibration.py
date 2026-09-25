"""Optional paid-valuation comparisons. Nothing here calls a provider."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal


def compare_valuations(
    *,
    case_id: str,
    native_eur: Decimal,
    provider: str,
    provider_eur: Decimal,
    recorded_at: datetime,
) -> dict[str, object]:
    """Store a difference. Paid figures are not used to train the native model."""

    gap = provider_eur - native_eur
    ratio = (gap / native_eur) if native_eur else Decimal("0")
    return {
        "case_id": case_id,
        "provider": provider,
        "native_eur": str(native_eur),
        "provider_eur": str(provider_eur),
        "absolute_error": str(abs(gap)),
        "percentage_difference": str(ratio.quantize(Decimal("0.0001"))),
        "recorded_at": recorded_at.isoformat(),
        "trained": False,
    }
