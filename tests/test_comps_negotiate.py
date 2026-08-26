from decimal import Decimal

from app.comps.matcher import match_comp
from app.economics.capital import allocate_capital
from app.economics.negotiate import negotiation_targets


def test_rejects_accessory_comp() -> None:
    result = match_comp("Sony A7 IV body", "Sony A7 IV battery only")
    assert result.accepted is False
    assert result.reason == "accessory"


def test_rejects_gm_vs_gm_ii_as_different_sku() -> None:
    result = match_comp("Sony FE 24-70 GM", "Sony FE 24-70 GM II")
    assert result.accepted is False


def test_negotiation_is_not_a_flat_percent() -> None:
    n = negotiation_targets(ask=Decimal("600"), max_buy=Decimal("510"), expected_profit=Decimal("80"))
    assert n.ideal_offer < n.acceptable_offer <= n.walk_away_price
    assert n.walk_away_price == Decimal("510.00")


def test_capital_skips_uncertified_and_oversize() -> None:
    picks = allocate_capital(
        [
            {"id": "a", "money_ready": True, "capital": Decimal("200"), "expected_profit": Decimal("80"), "downside": Decimal("10"), "profit_per_30": Decimal("40"), "category": "cameras"},
            {"id": "b", "money_ready": False, "capital": Decimal("200"), "expected_profit": Decimal("200"), "downside": Decimal("10"), "profit_per_30": Decimal("90"), "category": "cameras"},
        ],
        available=Decimal("5000"),
    )
    assert [p.opportunity_id for p in picks] == ["a"]
