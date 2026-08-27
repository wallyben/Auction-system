from decimal import Decimal
from types import SimpleNamespace

from app.paper.service import should_open_paper


def test_paper_opens_on_buy_ready() -> None:
    opp = SimpleNamespace(
        money_ready=True,
        engine_decision="BUY",
        decision="BUY",
        money_ready_decision="BUY_READY",
        gate_results={"failures": []},
        expected_profit_eur=Decimal("40"),
    )
    ok, reason = should_open_paper(opp)
    assert ok is True
    assert reason == "BUY_READY"


def test_paper_does_not_open_on_engine_buy_without_buy_ready() -> None:
    opp = SimpleNamespace(
        money_ready=False,
        engine_decision="BUY",
        decision="BUY",
        money_ready_decision="WATCH",
        gate_results={"failures": ["PRICE_EVIDENCE_PASS"]},
        expected_profit_eur=Decimal("40"),
    )
    ok, reason = should_open_paper(opp)
    assert ok is False
    assert reason == ""


def test_paper_opens_experimental_candidate() -> None:
    opp = SimpleNamespace(
        money_ready=False,
        engine_decision="REVIEW",
        decision="REVIEW",
        money_ready_decision="REVIEW",
        gate_results={"failures": ["PRICE_EVIDENCE_PASS"]},
        expected_profit_eur=Decimal("40"),
        provenance_pack={"experimental_paper": True},
        extras={},
    )
    ok, reason = should_open_paper(opp)
    assert ok is True
    assert reason == "EXPERIMENTAL"


def test_paper_skips_ignore() -> None:
    opp = SimpleNamespace(
        money_ready=False,
        engine_decision="IGNORE",
        decision="IGNORE",
        money_ready_decision="IGNORE",
        gate_results={"failures": ["MAX_BUY_PASS"]},
        expected_profit_eur=Decimal("-20"),
    )
    ok, _ = should_open_paper(opp)
    assert ok is False


def test_close_paper_rejects_listing_disappearance() -> None:
    from types import SimpleNamespace

    from app.paper.service import close_paper_trade

    trade = SimpleNamespace(status="open", notes="opened", observed_outcome=None)
    try:
        close_paper_trade(SimpleNamespace(flush=lambda: None), trade, outcome_kind="listing_disappeared")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "not a sale" in str(exc).lower()


def test_stale_valuation_algorithm_is_v2() -> None:
    from app.pipeline.service import revalue_all_active
    from app.valuation.version import VALUATION_ALGORITHM_VERSION

    assert VALUATION_ALGORITHM_VERSION.startswith("2.")
    assert callable(revalue_all_active)


def test_paper_skips_accessory_title() -> None:
    opp = SimpleNamespace(
        money_ready=True,
        engine_decision="BUY",
        decision="BUY",
        money_ready_decision="BUY_READY",
        gate_results={"failures": []},
        expected_profit_eur=Decimal("80"),
        title="Pioneer DDJ-FLX10 Stand",
    )
    ok, _ = should_open_paper(opp)
    assert ok is False
