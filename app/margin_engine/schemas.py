"""Pydantic schemas for margin engine calculations."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class MarginInput(BaseModel):
    """Input payload for maximum bid and margin calculations."""

    model_config = ConfigDict(str_strip_whitespace=True)

    expected_resale_price: Decimal
    auction_fee_percent: Decimal
    auction_fixed_fee: Decimal
    vat_scheme: Literal["margin", "standard"]
    vat_rate: Decimal
    logistics_cost: Decimal
    risk_percent: Decimal
    target_margin_percent: Decimal

    @field_validator(
        "expected_resale_price",
        "auction_fee_percent",
        "auction_fixed_fee",
        "vat_rate",
        "logistics_cost",
        "risk_percent",
        "target_margin_percent",
        mode="before",
    )
    @classmethod
    def parse_decimal_input(cls, value: Decimal | int | str) -> Decimal:
        """Parse numeric inputs as Decimal and reject floats."""
        if isinstance(value, Decimal):
            return value
        if isinstance(value, float):
            raise TypeError("Float values are not supported. Use Decimal-compatible input.")
        if isinstance(value, (int, str)):
            return Decimal(str(value))
        raise TypeError(f"Unsupported numeric value type: {type(value)!r}")

    @field_validator(
        "expected_resale_price",
        "auction_fee_percent",
        "auction_fixed_fee",
        "vat_rate",
        "logistics_cost",
        "risk_percent",
        "target_margin_percent",
    )
    @classmethod
    def validate_non_negative(cls, value: Decimal) -> Decimal:
        """Ensure all numeric inputs are non-negative."""
        if value < Decimal("0"):
            raise ValueError("Numeric values must be non-negative.")
        return value

    @field_validator("auction_fee_percent", "vat_rate", "risk_percent", "target_margin_percent")
    @classmethod
    def validate_percentage(cls, value: Decimal) -> Decimal:
        """Ensure percentage fields are represented as fractions between 0 and 1."""
        if value > Decimal("1"):
            raise ValueError("Percentage fields must be provided as fractions between 0 and 1.")
        return value
