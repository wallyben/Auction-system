from decimal import Decimal

from app.certification.engine import CategoryMetrics, evaluate_category_certification


def test_evaluator_refuses_without_realised_coverage() -> None:
    verdict = evaluate_category_certification(
        CategoryMetrics(
            category="cameras",
            listings=80,
            false_positive_rate=Decimal("0.02"),
            identity_exact_or_variant_rate=Decimal("0.94"),
            condition_reliable_rate=Decimal("0.90"),
            realised_comp_coverage=Decimal("0"),
            valuation_error_ok=True,
            exit_channel_credible=True,
            risk_controls_pass=True,
        )
    )
    assert verdict.certified is False
    assert any("realised_coverage" in r for r in verdict.reasons)


def test_evaluator_certifies_only_when_all_bars_met() -> None:
    verdict = evaluate_category_certification(
        CategoryMetrics(
            category="pro_av",
            listings=40,
            false_positive_rate=Decimal("0.02"),
            identity_exact_or_variant_rate=Decimal("0.95"),
            condition_reliable_rate=Decimal("0.90"),
            realised_comp_coverage=Decimal("0.60"),
            valuation_error_ok=True,
            exit_channel_credible=True,
            risk_controls_pass=True,
        )
    )
    assert verdict.certified is True
