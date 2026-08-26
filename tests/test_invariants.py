from decimal import Decimal

import pytest

from app.costs.landed import compute_landed_cost
from app.invariants.finance import InvariantError, assert_cost_stack, higher_cost_cannot_raise_max_buy, higher_price_cannot_raise_profit
from app.models.enums import Corridor


def test_net_cannot_exceed_gross() -> None:
    with pytest.raises(InvariantError):
        assert_cost_stack(
            purchase_price=Decimal("100"),
            all_in_cost=Decimal("120"),
            gross_sale=Decimal("200"),
            net_proceeds=Decimal("250"),
        )


def test_all_in_cannot_be_below_purchase() -> None:
    with pytest.raises(InvariantError):
        assert_cost_stack(
            purchase_price=Decimal("100"),
            all_in_cost=Decimal("80"),
            gross_sale=Decimal("200"),
            net_proceeds=Decimal("150"),
        )


def test_higher_fees_do_not_raise_max_buy() -> None:
    base = dict(
        purchase_price=Decimal("400"),
        currency_to_eur=Decimal("1"),
        corridor=Corridor.IE_DOMESTIC,
        shipping_listed=Decimal("10"),
        expected_resale_eur=Decimal("900"),
        quick_sale_eur=Decimal("800"),
        high_sale_eur=Decimal("1000"),
    )
    cheap = compute_landed_cost(**base, platform_fee_rate=Decimal("0.05"))
    dear = compute_landed_cost(**base, platform_fee_rate=Decimal("0.20"))
    higher_cost_cannot_raise_max_buy(cheap.max_purchase_eur, dear.max_purchase_eur)
    assert dear.max_purchase_eur <= cheap.max_purchase_eur
    assert dear.expected_profit_eur <= cheap.expected_profit_eur


def test_higher_purchase_lowers_profit() -> None:
    kwargs = dict(
        currency_to_eur=Decimal("1"),
        corridor=Corridor.IE_DOMESTIC,
        shipping_listed=Decimal("10"),
        expected_resale_eur=Decimal("900"),
        quick_sale_eur=Decimal("800"),
        high_sale_eur=Decimal("1000"),
    )
    low = compute_landed_cost(purchase_price=Decimal("300"), **kwargs)
    high = compute_landed_cost(purchase_price=Decimal("500"), **kwargs)
    higher_price_cannot_raise_profit(low.expected_profit_eur, high.expected_profit_eur)
