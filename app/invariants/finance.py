"""Assertions that prevent impossible money numbers from becoming decisions."""

from __future__ import annotations

from decimal import Decimal

from app.core.money import ZERO, as_decimal, money


class InvariantError(AssertionError):
    """A calculated economic value is internally inconsistent."""


def assert_cost_stack(
    *,
    purchase_price: Decimal,
    all_in_cost: Decimal,
    gross_sale: Decimal,
    net_proceeds: Decimal,
    expected_profit: Decimal | None = None,
) -> None:
    purchase_price = as_decimal(purchase_price)
    all_in_cost = as_decimal(all_in_cost)
    gross_sale = as_decimal(gross_sale)
    net_proceeds = as_decimal(net_proceeds)
    if all_in_cost < purchase_price:
        raise InvariantError(f"all_in_cost {all_in_cost} < purchase_price {purchase_price}")
    if net_proceeds > gross_sale:
        raise InvariantError(f"net_proceeds {net_proceeds} > gross_sale {gross_sale}")
    if expected_profit is not None:
        reconstructed = money(net_proceeds - all_in_cost)
        if abs(reconstructed - as_decimal(expected_profit)) > Decimal("0.05"):
            raise InvariantError(
                f"expected_profit {expected_profit} != net-all_in {reconstructed}"
            )


def assert_money_ready(
    *,
    expected_profit: Decimal,
    downside_profit: Decimal,
    min_downside: Decimal,
    max_buy: Decimal,
    asking: Decimal | None,
) -> None:
    if expected_profit <= ZERO:
        raise InvariantError("BUY_READY requires expected_profit > 0")
    if downside_profit < as_decimal(min_downside):
        raise InvariantError("BUY_READY requires downside_profit >= configured floor")
    if asking is not None and max_buy > ZERO and asking > max_buy:
        raise InvariantError("BUY_READY asking exceeds max_buy")


def higher_cost_cannot_raise_max_buy(base_max: Decimal, higher_cost_max: Decimal) -> None:
    if higher_cost_max > base_max:
        raise InvariantError(f"max_buy rose from {base_max} to {higher_cost_max} when costs increased")


def higher_price_cannot_raise_profit(low_price_profit: Decimal, high_price_profit: Decimal) -> None:
    if high_price_profit > low_price_profit:
        raise InvariantError("expected profit rose when purchase price rose")
