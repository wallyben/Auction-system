"""Margin engine module for deterministic bid calculations."""

from app.margin_engine.calculator import calculate_margin
from app.margin_engine.schemas import MarginInput

__all__ = ["MarginInput", "calculate_margin"]
