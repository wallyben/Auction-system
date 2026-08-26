"""Conservative expected value. Downside is first-class, not a footnote."""

from __future__ import annotations

from decimal import Decimal

from app.core.money import money


def expected_value(
    *,
    base_profit: Decimal,
    upside_profit: Decimal,
    downside_profit: Decimal,
    failure_loss: Decimal,
    p_base: Decimal = Decimal("0.55"),
    p_up: Decimal = Decimal("0.15"),
    p_down: Decimal = Decimal("0.22"),
    p_fail: Decimal = Decimal("0.08"),
) -> Decimal:
    total = p_base + p_up + p_down + p_fail
    if total <= 0:
        return money(0)
    return money(
        (p_base * base_profit + p_up * upside_profit + p_down * downside_profit + p_fail * failure_loss) / total
    )
