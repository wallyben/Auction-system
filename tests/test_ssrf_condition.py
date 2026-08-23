import pytest

from app.condition.category import assess_category_condition
from app.models.enums import ConditionGrade
from app.security.ssrf import assert_public_url


def test_ssrf_blocks_localhost() -> None:
    with pytest.raises(ValueError):
        assert_public_url("http://127.0.0.1/admin")


def test_ssrf_blocks_unknown_host() -> None:
    with pytest.raises(ValueError):
        assert_public_url("https://donedeal.ie/listing/1")


def test_fungus_is_not_excellent() -> None:
    result = assess_category_condition("excellent", "some fungus on rear element", "lenses")
    assert result.grade in {ConditionGrade.FAIR, ConditionGrade.POOR, ConditionGrade.FOR_PARTS}
    assert result.refurb_high_eur >= result.refurb_low_eur
