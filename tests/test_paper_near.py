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


def test_paper_opens_on_engine_buy() -> None:
    opp = SimpleNamespace(
        money_ready=False,
        engine_decision="BUY",
        decision="BUY",
        money_ready_decision="WATCH",
        gate_results={"failures": ["PRICE_EVIDENCE_PASS"]},
        expected_profit_eur=Decimal("40"),
    )
    ok, reason = should_open_paper(opp)
    assert ok is True
    assert reason == "ENGINE_BUY"


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
