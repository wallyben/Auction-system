from decimal import Decimal

from app.decision.gates import apply_money_ready_gates
from app.models.enums import Decision, IdentityLevel, MoneyReadyDecision


def _gates(**overrides):
    data = dict(
        engine=Decision.BUY,
        identity_level=IdentityLevel.EXACT,
        identity_confidence=Decimal("0.92"),
        condition_confidence=Decimal("0.80"),
        valuation_confidence=Decimal("0.85"),
        comparable_count=5,
        realised_count=2,
        local_count=1,
        liquidity_confidence=Decimal("0.60"),
        expected_days=12,
        expected_profit=Decimal("120"),
        downside_profit=Decimal("20"),
        roi=Decimal("0.30"),
        risk_score=Decimal("0.20"),
        high_risk=False,
        asking=Decimal("400"),
        max_buy=Decimal("500"),
        all_in_cost=Decimal("450"),
        purchase_price=Decimal("400"),
        gross_sale=Decimal("700"),
        net_proceeds=Decimal("570"),
        category="cameras",
        category_certified=True,
        exit_present=True,
        provenance_complete=True,
        source_fresh=True,
        tax_modelled=True,
    )
    data.update(overrides)
    return apply_money_ready_gates(**data)


def test_buy_ready_requires_all_gates() -> None:
    result = _gates()
    # SAFE_START default max purchase is €250, asking 400 fails SAFE_START.
    assert result.money_ready is False
    assert "SAFE_START_PASS" in result.failures


def test_buy_ready_can_pass_inside_safe_start(monkeypatch) -> None:
    from app.decision import gates as gates_mod

    monkeypatch.setattr(gates_mod.settings, "safe_start_mode", True)
    monkeypatch.setattr(gates_mod.settings, "safe_start_max_purchase_eur", "250")
    result = _gates(
        asking=Decimal("200"),
        purchase_price=Decimal("200"),
        all_in_cost=Decimal("220"),
        expected_profit=Decimal("80"),
        net_proceeds=Decimal("300"),
        downside_profit=Decimal("10"),
    )
    assert result.money_ready is True
    assert result.money_ready_decision.value == "BUY_READY"


def test_negative_downside_blocks_buy_ready() -> None:
    result = _gates(downside_profit=Decimal("-10"), asking=Decimal("200"), all_in_cost=Decimal("220"), purchase_price=Decimal("200"))
    assert result.money_ready is False
    assert result.money_ready_decision != MoneyReadyDecision.BUY_READY


def test_no_realised_comp_forces_review() -> None:
    result = _gates(realised_count=0, asking=Decimal("200"), purchase_price=Decimal("200"), all_in_cost=Decimal("220"))
    assert result.money_ready is False
    assert result.money_ready_decision == MoneyReadyDecision.REVIEW


def test_sandbox_source_cannot_be_buy_ready(monkeypatch) -> None:
    from app.decision import gates as gates_mod

    monkeypatch.setattr(gates_mod.settings, "safe_start_mode", True)
    monkeypatch.setattr(gates_mod.settings, "safe_start_max_purchase_eur", "250")
    result = _gates(
        asking=Decimal("200"),
        purchase_price=Decimal("200"),
        all_in_cost=Decimal("220"),
        expected_profit=Decimal("80"),
        net_proceeds=Decimal("300"),
        downside_profit=Decimal("10"),
        sandbox_source=True,
    )
    assert result.money_ready is False
    assert "PRODUCTION_SOURCE_PASS" in result.failures


def test_high_risk_blocks_buy_ready() -> None:
    result = _gates(high_risk=True, risk_score=Decimal("0.80"), asking=Decimal("200"), purchase_price=Decimal("200"), all_in_cost=Decimal("220"))
    assert result.money_ready is False
