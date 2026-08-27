from decimal import Decimal

from app.liquidity.engine import estimate_liquidity
from app.opportunity.ranking import RANK_BUY_READY, commercial_rank
from app.models.enums import IdentityLevel, MoneyReadyDecision
from app.sold.importers import detect_kind
from app.valuation.engine import value_from_comps
from app.valuation.version import VALUATION_ALGORITHM_VERSION


def test_liquidity_without_realised_is_prior_not_measured() -> None:
    result = estimate_liquidity(comparable_count=8, realised_count=0, local_count=0, category="cameras", is_lot=False)
    assert result.kind == "MARKET_PRIOR"
    assert result.expected_days_to_sale is None


def test_liquidity_with_realised_can_be_measured() -> None:
    result = estimate_liquidity(comparable_count=10, realised_count=5, local_count=2, category="cameras", is_lot=False)
    assert result.kind == "MEASURED_LIQUIDITY"
    assert result.expected_days_to_sale is not None


def test_buy_ready_ranks_above_watch() -> None:
    buy = commercial_rank(
        money_ready_decision=MoneyReadyDecision.BUY_READY,
        identity_level=IdentityLevel.EXACT,
        identity_confidence=Decimal("0.95"),
        realised_count=5,
        binding_count=5,
        expected_profit=Decimal("120"),
        valuation_confidence=Decimal("0.86"),
        liquidity_score=Decimal("0.7"),
        downside_profit=Decimal("30"),
    )
    assert buy.group == RANK_BUY_READY
    assert buy.score > Decimal("0")


def test_empty_comps_are_versioned_unvalidated() -> None:
    result = value_from_comps([])
    assert result.algorithm_version == VALUATION_ALGORITHM_VERSION
    assert result.value_status == "UNVALIDATED_VALUE"
    assert result.expected_sale_eur == 0


def test_terapeak_aggregate_is_not_ticket_export() -> None:
    csv = "Title,Avg sold price,Sell through,Sold items\nSony A7 IV,1100,0.42,18\n"
    assert detect_kind(csv) == "terapeak_aggregate"
