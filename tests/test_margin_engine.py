"""Unit tests for deterministic margin engine calculations."""

from __future__ import annotations

from decimal import Decimal

from app.margin_engine.calculator import calculate_margin
from app.margin_engine.schemas import MarginInput


def _build_input(**overrides: Decimal | str) -> MarginInput:
    data: dict[str, Decimal | str] = {
        "expected_resale_price": Decimal("10000"),
        "auction_fee_percent": Decimal("0.10"),
        "auction_fixed_fee": Decimal("100"),
        "vat_scheme": "standard",
        "vat_rate": Decimal("0.20"),
        "logistics_cost": Decimal("500"),
        "risk_percent": Decimal("0.05"),
        "target_margin_percent": Decimal("0.15"),
    }
    data.update(overrides)
    return MarginInput(**data)


def test_standard_vat_scenario() -> None:
    margin_input = _build_input()

    result = calculate_margin(margin_input)

    assert result["max_bid"] == Decimal("6076.92")
    assert result["projected_profit_at_max_bid"] == Decimal("1500.00")
    assert result["risk_discount"] == Decimal("500.00")
    assert result["breakdown"]["auction_fee"] == Decimal("707.69")
    assert result["breakdown"]["vat"] == Decimal("1215.38")
    assert result["breakdown"]["target_margin"] == Decimal("1500.00")


def test_margin_vat_scenario() -> None:
    margin_input = _build_input(
        expected_resale_price=Decimal("8000"),
        auction_fee_percent=Decimal("0.12"),
        auction_fixed_fee=Decimal("80"),
        vat_scheme="margin",
        vat_rate=Decimal("0.20"),
        logistics_cost=Decimal("300"),
        risk_percent=Decimal("0.03"),
        target_margin_percent=Decimal("0.10"),
    )

    result = calculate_margin(margin_input)

    assert result["max_bid"] == Decimal("5673.91")
    assert result["projected_profit_at_max_bid"] == Decimal("800.00")
    assert result["risk_discount"] == Decimal("240.00")
    assert result["breakdown"]["auction_fee"] == Decimal("760.87")
    assert result["breakdown"]["vat"] == Decimal("465.22")
    assert result["breakdown"]["target_margin"] == Decimal("800.00")


def test_high_risk_case() -> None:
    margin_input = _build_input(
        expected_resale_price=Decimal("5000"),
        auction_fixed_fee=Decimal("50"),
        logistics_cost=Decimal("200"),
        risk_percent=Decimal("0.40"),
        target_margin_percent=Decimal("0.10"),
    )

    result = calculate_margin(margin_input)

    assert result["max_bid"] == Decimal("3269.23")
    assert result["projected_profit_at_max_bid"] == Decimal("500.00")
    assert result["risk_discount"] == Decimal("2000.00")
    assert result["breakdown"]["risk_discount"] == Decimal("2000.00")


def test_zero_logistics_case() -> None:
    margin_input = _build_input(
        expected_resale_price=Decimal("3000"),
        auction_fee_percent=Decimal("0.08"),
        auction_fixed_fee=Decimal("20"),
        logistics_cost=Decimal("0"),
        risk_percent=Decimal("0.02"),
        target_margin_percent=Decimal("0.10"),
    )

    result = calculate_margin(margin_input)

    assert result["max_bid"] == Decimal("2093.75")
    assert result["projected_profit_at_max_bid"] == Decimal("300.00")
    assert result["breakdown"]["logistics_cost"] == Decimal("0.00")


def test_negative_max_bid_edge_case() -> None:
    margin_input = _build_input(
        expected_resale_price=Decimal("1000"),
        auction_fixed_fee=Decimal("300"),
        logistics_cost=Decimal("600"),
        risk_percent=Decimal("0.10"),
        target_margin_percent=Decimal("0.20"),
    )

    result = calculate_margin(margin_input)

    assert result["max_bid"] == Decimal("0.00")
    assert result["projected_profit_at_max_bid"] == Decimal("100.00")
    assert result["breakdown"]["target_margin"] == Decimal("200.00")


def test_resale_equals_purchase_edge_case() -> None:
    margin_input = _build_input(
        expected_resale_price=Decimal("1000"),
        auction_fee_percent=Decimal("0"),
        auction_fixed_fee=Decimal("0"),
        vat_scheme="margin",
        vat_rate=Decimal("0.20"),
        logistics_cost=Decimal("0"),
        risk_percent=Decimal("0"),
        target_margin_percent=Decimal("0"),
    )

    result = calculate_margin(margin_input)

    assert result["max_bid"] == Decimal("1000.00")
    assert result["projected_profit_at_max_bid"] == Decimal("0.00")
    assert result["breakdown"]["vat"] == Decimal("0.00")


def test_precision_rounding_is_two_decimals() -> None:
    margin_input = _build_input(
        expected_resale_price=Decimal("1000"),
        auction_fee_percent=Decimal("0"),
        auction_fixed_fee=Decimal("899.995"),
        vat_scheme="standard",
        vat_rate=Decimal("0"),
        logistics_cost=Decimal("0"),
        risk_percent=Decimal("0.1234"),
        target_margin_percent=Decimal("0"),
    )

    result = calculate_margin(margin_input)

    assert result["max_bid"] == Decimal("100.00")
    assert result["projected_profit_at_max_bid"] == Decimal("0.01")
    assert result["risk_discount"] == Decimal("123.40")

    assert result["max_bid"].as_tuple().exponent == -2
    assert result["projected_profit_at_max_bid"].as_tuple().exponent == -2
    assert result["risk_discount"].as_tuple().exponent == -2
    for value in result["breakdown"].values():
        assert value.as_tuple().exponent == -2
