"""Decimal money helpers. Floats are rejected at the boundary."""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

TWOPLACES = Decimal("0.01")
FOURPLACES = Decimal("0.0001")
ZERO = Decimal("0")
ONE = Decimal("1")


def as_decimal(value: Decimal | int | str | None, *, allow_none: bool = False) -> Decimal:
    """Parse a Decimal-compatible value and reject floats."""
    if value is None:
        if allow_none:
            return ZERO
        raise ValueError("Numeric value is required.")
    if isinstance(value, float):
        raise TypeError("Float values are not supported. Use Decimal-compatible input.")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money(value: Decimal | int | str | None, *, rounding: str = ROUND_HALF_UP) -> Decimal:
    """Quantize to cents."""
    return as_decimal(value, allow_none=True).quantize(TWOPLACES, rounding=rounding)


def money_down(value: Decimal | int | str) -> Decimal:
    """Quantize to cents rounding down — used for max-bid safety."""
    return as_decimal(value).quantize(TWOPLACES, rounding=ROUND_DOWN)


def rate(value: Decimal | int | str | None) -> Decimal:
    """Parse a non-negative fraction."""
    parsed = as_decimal(value, allow_none=True)
    if parsed < ZERO:
        raise ValueError("Rates must be non-negative.")
    return parsed


as_decimal = as_decimal
ONE = ONE if "ONE" in globals() else Decimal("1")
