"""BUY_READY is substantially harder than engine BUY. Low-quality data never buys."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.core.config import settings
from app.core.money import ZERO, as_decimal, money
from app.invariants.finance import InvariantError, assert_cost_stack, assert_money_ready
from app.models.enums import Decision, IdentityLevel, MoneyReadyDecision


GATES = (
    "PRODUCT_IDENTITY_PASS",
    "CONDITION_PASS",
    "PRICE_EVIDENCE_PASS",
    "LOCALISATION_PASS",
    "EXIT_CHANNEL_PASS",
    "LIQUIDITY_PASS",
    "COST_PASS",
    "TAX_PASS",
    "RISK_PASS",
    "SOURCE_FRESHNESS_PASS",
    "DOWNSIDE_PASS",
    "MAX_BUY_PASS",
    "DATA_PROVENANCE_PASS",
    "CATEGORY_CERT_PASS",
    "SAFE_START_PASS",
)


@dataclass(slots=True)
class GateResult:
    engine_decision: Decision
    money_ready: bool
    money_ready_decision: MoneyReadyDecision
    gates: dict[str, bool]
    failures: list[str] = field(default_factory=list)
    why: str = ""


def apply_money_ready_gates(
    *,
    engine: Decision,
    identity_level: IdentityLevel,
    identity_confidence: Decimal,
    condition_confidence: Decimal,
    valuation_confidence: Decimal,
    comparable_count: int,
    realised_count: int,
    local_count: int,
    liquidity_confidence: Decimal,
    expected_days: int | None,
    expected_profit: Decimal,
    downside_profit: Decimal,
    roi: Decimal,
    risk_score: Decimal,
    high_risk: bool,
    asking: Decimal | None,
    max_buy: Decimal,
    all_in_cost: Decimal,
    purchase_price: Decimal,
    gross_sale: Decimal,
    net_proceeds: Decimal,
    category: str | None,
    category_certified: bool,
    exit_present: bool,
    provenance_complete: bool,
    source_fresh: bool,
    tax_modelled: bool,
    listing_type: str = "fixed",
) -> GateResult:
    min_id = as_decimal(settings.buy_ready_min_identity)
    min_cond = as_decimal(settings.buy_ready_min_condition)
    min_val = as_decimal(settings.buy_ready_min_valuation)
    min_down = as_decimal(settings.min_downside_margin)
    gates = {name: False for name in GATES}
    gates["PRODUCT_IDENTITY_PASS"] = identity_level in {IdentityLevel.EXACT, IdentityLevel.VARIANT} and identity_confidence >= min_id
    gates["CONDITION_PASS"] = condition_confidence >= min_cond
    strong = comparable_count >= settings.buy_ready_min_comps
    realised_ok = realised_count >= 1 or not settings.buy_ready_require_realised
    if realised_count == 0:
        # No realised comp: only pass evidence if sample is thick and owner overrode require_realised.
        gates["PRICE_EVIDENCE_PASS"] = strong and realised_ok and valuation_confidence >= min_val
    else:
        gates["PRICE_EVIDENCE_PASS"] = strong and valuation_confidence >= min_val
    gates["LOCALISATION_PASS"] = local_count >= 1 or valuation_confidence >= Decimal("0.85")
    gates["EXIT_CHANNEL_PASS"] = exit_present
    days_ok = expected_days is None or expected_days <= settings.max_days_to_sale
    gates["LIQUIDITY_PASS"] = liquidity_confidence >= Decimal("0.35") and days_ok
    try:
        assert_cost_stack(
            purchase_price=purchase_price,
            all_in_cost=all_in_cost,
            gross_sale=gross_sale,
            net_proceeds=net_proceeds,
            expected_profit=expected_profit,
        )
        gates["COST_PASS"] = True
    except InvariantError:
        gates["COST_PASS"] = False
    gates["TAX_PASS"] = tax_modelled
    gates["RISK_PASS"] = (not high_risk) and risk_score < Decimal("0.45")
    gates["SOURCE_FRESHNESS_PASS"] = source_fresh
    gates["DOWNSIDE_PASS"] = downside_profit >= min_down
    under_max = asking is None or asking <= max_buy
    gates["MAX_BUY_PASS"] = under_max and max_buy > ZERO
    gates["DATA_PROVENANCE_PASS"] = provenance_complete
    gates["CATEGORY_CERT_PASS"] = category_certified or settings.owner_override_uncertified
    safe_limit = as_decimal(settings.safe_start_max_purchase_eur if settings.safe_start_mode else settings.max_purchase_eur)
    safe_conf = as_decimal(settings.safe_start_min_confidence) if settings.safe_start_mode else as_decimal(settings.min_confidence)
    purchase = asking or purchase_price
    gates["SAFE_START_PASS"] = (
        purchase <= safe_limit
        and valuation_confidence >= safe_conf
        and downside_profit >= ZERO
    )
    failures = [name for name, ok in gates.items() if not ok]
    money_ready = False
    action = MoneyReadyDecision.REVIEW
    if engine is Decision.IGNORE:
        action = MoneyReadyDecision.IGNORE
    elif engine is Decision.REVIEW or failures:
        if engine is Decision.WATCH or (
            expected_profit >= as_decimal(settings.min_profit_eur) * Decimal("0.5")
            and not high_risk
        ):
            action = MoneyReadyDecision.WATCH if "RISK_PASS" in gates and gates["RISK_PASS"] else MoneyReadyDecision.REVIEW
        if high_risk or identity_level in {IdentityLevel.UNKNOWN, IdentityLevel.CATEGORY}:
            action = MoneyReadyDecision.REVIEW
        if engine is Decision.IGNORE:
            action = MoneyReadyDecision.IGNORE
        if expected_profit < ZERO and (asking or ZERO) > (max_buy or ZERO):
            action = MoneyReadyDecision.IGNORE
    if engine is Decision.BUY and not failures:
        try:
            assert_money_ready(
                expected_profit=expected_profit,
                downside_profit=downside_profit,
                min_downside=min_down,
                max_buy=max_buy,
                asking=asking,
            )
            money_ready = True
            action = MoneyReadyDecision.BUY_READY
        except InvariantError:
            action = MoneyReadyDecision.REVIEW
            failures.append("INVARIANT")
    if not gates["PRICE_EVIDENCE_PASS"] and realised_count == 0:
        action = MoneyReadyDecision.REVIEW
        money_ready = False
    if high_risk:
        money_ready = False
        if action is MoneyReadyDecision.BUY_READY:
            action = MoneyReadyDecision.REVIEW
    why = (
        f"engine={engine.value} money_ready={action.value}. "
        + ("All gates passed." if money_ready else "Failed: " + ", ".join(failures))
    )
    return GateResult(engine, money_ready, action, gates, failures, why)
