"""Condition normalisation."""

from decimal import Decimal

from app.condition.engine import assess_condition
from app.models.enums import ConditionGrade


def test_excellent_language() -> None:
    result = assess_condition("excellent condition", "mint, barely used")
    assert result.grade in {ConditionGrade.EXCELLENT, ConditionGrade.VERY_GOOD, ConditionGrade.NEW}
    assert result.confidence >= Decimal("0.50")


def test_parts_only_is_for_parts() -> None:
    result = assess_condition("for parts or not working", "spares repair cracked lcd")
    assert result.grade in {ConditionGrade.FOR_PARTS, ConditionGrade.POOR, ConditionGrade.FAIR, ConditionGrade.UNKNOWN}


def test_structured_ebay_used_clears_buy_ready_condition_bar() -> None:
    result = assess_condition("Used", "", condition_id="3000")
    assert result.grade == ConditionGrade.GOOD
    assert result.confidence >= Decimal("0.75")


def test_structured_used_name_without_id() -> None:
    result = assess_condition("Used")
    assert result.grade == ConditionGrade.GOOD
    assert result.confidence >= Decimal("0.75")


def test_parts_overrides_structured_used() -> None:
    result = assess_condition("Used", "for parts not working shutter broken", condition_id="3000")
    assert result.grade == ConditionGrade.FOR_PARTS
