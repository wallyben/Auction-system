"""Deterministic Decimal-based margin and max-bid calculations."""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import TypedDict

from app.margin_engine.schemas import MarginInput

TWOPLACES = Decimal("0.01")
ZERO = Decimal("0")
ONE = Decimal("1")


class MarginCalculationResult(TypedDict):
    """Structured response for margin calculations."""

    max_bid: Decimal
    projected_profit_at_max_bid: Decimal
    risk_discount: Decimal
    breakdown: dict[str, Decimal]


def _quantize_money(value: Decimal, *, rounding: str = ROUND_HALF_UP) -> Decimal:
    """Quantize monetary values to two decimal places."""
    return value.quantize(TWOPLACES, rounding=rounding)


def _calculate_auction_fee(input_data: MarginInput, hammer_price: Decimal) -> Decimal:
    """Calculate total auction fee."""
    return (hammer_price * input_data.auction_fee_percent) + input_data.auction_fixed_fee


def _calculate_vat(input_data: MarginInput, hammer_price: Decimal) -> Decimal:
    """Calculate VAT using the configured VAT scheme."""
    if input_data.vat_scheme == "standard":
        return hammer_price * input_data.vat_rate
    return (input_data.expected_resale_price - hammer_price) * input_data.vat_rate


def _calculate_profit(input_data: MarginInput, hammer_price: Decimal) -> Decimal:
    """Calculate projected profit for a given hammer price."""
    auction_fee = _calculate_auction_fee(input_data, hammer_price)
    vat = _calculate_vat(input_data, hammer_price)
    return (
        input_data.expected_resale_price
        - auction_fee
        - vat
        - input_data.logistics_cost
        - hammer_price
    )


def _target_margin_value(input_data: MarginInput) -> Decimal:
    """Calculate the target margin value."""
    return input_data.expected_resale_price * input_data.target_margin_percent


def _risk_discount_value(input_data: MarginInput) -> Decimal:
    """Calculate risk discount value."""
    return input_data.expected_resale_price * input_data.risk_percent


def _solve_max_bid_raw(input_data: MarginInput) -> Decimal:
    """Solve the linear max bid equation before quantization."""
    target_margin = _target_margin_value(input_data)

    if input_data.vat_scheme == "standard":
        numerator = (
            input_data.expected_resale_price
            - input_data.auction_fixed_fee
            - input_data.logistics_cost
            - target_margin
        )
        denominator = ONE + input_data.auction_fee_percent + input_data.vat_rate
    else:
        numerator = (
            (input_data.expected_resale_price * (ONE - input_data.vat_rate))
            - input_data.auction_fixed_fee
            - input_data.logistics_cost
            - target_margin
        )
        denominator = ONE + input_data.auction_fee_percent - input_data.vat_rate

    if denominator <= ZERO:
        raise ValueError("Invalid input causes non-positive max bid denominator.")

    if numerator <= ZERO:
        return ZERO

    return numerator / denominator


def calculate_margin(input_data: MarginInput) -> MarginCalculationResult:
    """
    Calculate maximum safe bid and financial breakdown.

    The max bid is solved from:
        projected_profit >= target_margin
    """
    raw_max_bid = _solve_max_bid_raw(input_data)
    max_bid = _quantize_money(raw_max_bid, rounding=ROUND_DOWN)

    auction_fee = _calculate_auction_fee(input_data, max_bid)
    vat = _calculate_vat(input_data, max_bid)
    target_margin = _target_margin_value(input_data)
    risk_discount = _risk_discount_value(input_data)
    projected_profit = _calculate_profit(input_data, max_bid)

    quantized_max_bid = _quantize_money(max_bid)
    quantized_projected_profit = _quantize_money(projected_profit)
    quantized_risk_discount = _quantize_money(risk_discount)

    breakdown: dict[str, Decimal] = {
        "expected_resale_price": _quantize_money(input_data.expected_resale_price),
        "hammer_price": quantized_max_bid,
        "auction_fee": _quantize_money(auction_fee),
        "vat": _quantize_money(vat),
        "logistics_cost": _quantize_money(input_data.logistics_cost),
        "target_margin": _quantize_money(target_margin),
        "risk_discount": quantized_risk_discount,
        "projected_profit": quantized_projected_profit,
    }

    return {
        "max_bid": quantized_max_bid,
        "projected_profit_at_max_bid": quantized_projected_profit,
        "risk_discount": quantized_risk_discount,
        "breakdown": breakdown,
    }
