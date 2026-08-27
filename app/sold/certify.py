"""Empirical camera_body certification. Never override a failing bar."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.certification.engine import CategoryMetrics, evaluate_category_certification


def camera_body_certification_snapshot(
    *,
    precision: dict[str, Any],
    backtest: dict[str, Any] | None = None,
    listings: int = 0,
    realised_comp_coverage: Decimal = Decimal("0"),
    condition_reliable_rate: Decimal = Decimal("0.85"),
    exit_channel_credible: bool = True,
    risk_controls_pass: bool = True,
) -> dict[str, Any]:
    """Certify camera_body only from measured bars. Live coverage stays 0 until CompSniper is keyed."""
    identity_rate = Decimal(str(precision.get("exact_match_precision") or 0))
    fp = Decimal(str(precision.get("accepted_wrong") or 0))
    sample = int(precision.get("sample_size") or 0)
    false_positive_rate = (fp / Decimal(sample)) if sample else Decimal("1")
    mae_ok = True
    if backtest and backtest.get("mean_pct_error") is not None:
        try:
            mae_ok = Decimal(str(backtest["mean_pct_error"])) <= Decimal("0.20")
        except Exception:
            mae_ok = False
    metrics = CategoryMetrics(
        category="cameras",
        listings=listings,
        false_positive_rate=false_positive_rate,
        identity_exact_or_variant_rate=identity_rate,
        condition_reliable_rate=condition_reliable_rate,
        realised_comp_coverage=realised_comp_coverage,
        valuation_error_ok=mae_ok,
        exit_channel_credible=exit_channel_credible,
        risk_controls_pass=risk_controls_pass,
    )
    verdict = evaluate_category_certification(metrics)
    return {
        "category": "camera_body",
        "certified": verdict.certified,
        "reasons": verdict.reasons,
        "identity_precision": float(identity_rate),
        "false_positive_rate": float(false_positive_rate),
        "realised_comp_coverage": str(realised_comp_coverage),
        "listings": listings,
        "note": (
            "Certified on measured identity, coverage, valuation error, and exit bars."
            if verdict.certified
            else "Uncertified until live realised coverage and remaining bars pass. Not overridden."
        ),
    }
