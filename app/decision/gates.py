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
    "PRODUCTION_SOURCE_PASS",
)


def _is_camera_body(product_class: str | None, category: str | None) -> bool:
    klass = (product_class or "").lower()
    if klass == "camera_body":
        return True
    return False


def _safe_start_pass(
    *,
    purchase: Decimal,
    valuation_confidence: Decimal,
    safe_conf: Decimal,
    downside_profit: Decimal,
    realised_count: int,
    roi: Decimal,
    liquidity_confidence: Decimal,
    product_class: str | None,
    category: str | None,
    liquidity_kind: str | None,
    all_in_cost: Decimal,
    p25_sale_eur: Decimal | None,
) -> bool:
    """SAFE_START is a capital-at-risk programme, not a universal €250 SKU cap.

    Uncertified categories keep the €250 purchase cap.
    camera_body uses an evidence-driven starting limit: thick realised sample,
    known velocity, non-negative p25 downside, and a conservative purchase cap
    below the full book limit. The camera cap is not tuned to a live listing.
    """
    if not settings.safe_start_mode:
        return purchase <= as_decimal(settings.max_purchase_eur) and downside_profit >= ZERO
    if not _is_camera_body(product_class, category):
        return (
            purchase <= as_decimal(settings.safe_start_max_purchase_eur)
            and valuation_confidence >= safe_conf
            and downside_profit >= ZERO
        )
    camera_limit = as_decimal(settings.safe_start_camera_max_purchase_eur)
    min_realised = int(getattr(settings, "safe_start_camera_min_realised", 8) or 8)
    max_loss = as_decimal(settings.max_single_item_loss_eur)
    min_roi = as_decimal(settings.min_roi)
    velocity_known = (liquidity_kind or "") not in {"", "UNKNOWN"}
    p25 = p25_sale_eur if p25_sale_eur is not None else ZERO
    # Capital at risk on the p25 sale: all-in cost minus p25 gross (conservative;
    # fees still sit in downside_profit which must also be >= 0).
    capital_at_risk = all_in_cost - p25 if p25 > ZERO else all_in_cost
    if capital_at_risk < ZERO:
        capital_at_risk = ZERO
    return (
        purchase <= camera_limit
        and valuation_confidence >= safe_conf
        and downside_profit >= ZERO
        and realised_count >= min_realised
        and roi >= min_roi
        and liquidity_confidence >= Decimal("0.40")
        and velocity_known
        and capital_at_risk <= max_loss
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
    sandbox_source: bool = False,
    local_market_method: str = "",
    uk_comp_count: int = 0,
    localisation_confidence: Decimal | None = None,
    sold_evidence_fresh: bool = True,
    valuation_anomaly: bool = False,
    product_class: str | None = None,
    liquidity_kind: str | None = None,
    p25_sale_eur: Decimal | None = None,
    book_current: bool = True,
) -> GateResult:
    from app.identity.product_class import ACCESSORY_CLASSES, CAMERA_BODY

    min_id = as_decimal(settings.buy_ready_min_identity)
    min_cond = as_decimal(settings.buy_ready_min_condition)
    min_val = as_decimal(settings.buy_ready_min_valuation)
    min_down = as_decimal(settings.min_downside_margin)
    gates = {name: False for name in GATES}
    klass = (product_class or "").lower()
    identity_ok = identity_level in {IdentityLevel.EXACT, IdentityLevel.VARIANT} and identity_confidence >= min_id
    if klass in ACCESSORY_CLASSES or klass in {"accessory", "game", "consumable"}:
        identity_ok = False
    elif (category or "").lower() in {"cameras", "camera", "camera_body"} or klass == CAMERA_BODY:
        identity_ok = identity_ok and klass == CAMERA_BODY
    gates["PRODUCT_IDENTITY_PASS"] = identity_ok
    gates["CONDITION_PASS"] = condition_confidence >= min_cond
    strong = comparable_count >= settings.buy_ready_min_comps
    realised_ok = realised_count >= 1 or not settings.buy_ready_require_realised
    if realised_count == 0:
        # No realised comp: only pass evidence if sample is thick and owner overrode require_realised.
        gates["PRICE_EVIDENCE_PASS"] = strong and realised_ok and valuation_confidence >= min_val
    else:
        gates["PRICE_EVIDENCE_PASS"] = strong and valuation_confidence >= min_val and sold_evidence_fresh
    uk_proxy_ok = (
        (local_market_method or "") == "UK_REALIZED_PROXY"
        and uk_comp_count >= settings.buy_ready_min_comps
        and (localisation_confidence or ZERO) >= Decimal("0.40")
    )
    # High valuation confidence is not a substitute for local or UK-proxy evidence.
    gates["LOCALISATION_PASS"] = local_count >= 1 or uk_proxy_ok
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
    gates["SOURCE_FRESHNESS_PASS"] = source_fresh and sold_evidence_fresh
    gates["DOWNSIDE_PASS"] = downside_profit >= min_down
    under_max = asking is None or asking <= max_buy
    gates["MAX_BUY_PASS"] = under_max and max_buy > ZERO
    gates["DATA_PROVENANCE_PASS"] = provenance_complete and not valuation_anomaly and book_current
    gates["CATEGORY_CERT_PASS"] = category_certified or settings.owner_override_uncertified
    safe_conf = as_decimal(settings.safe_start_min_confidence) if settings.safe_start_mode else as_decimal(settings.min_confidence)
    purchase = asking or purchase_price
    gates["SAFE_START_PASS"] = _safe_start_pass(
        purchase=purchase,
        valuation_confidence=valuation_confidence,
        safe_conf=safe_conf,
        downside_profit=downside_profit,
        realised_count=realised_count,
        roi=roi,
        liquidity_confidence=liquidity_confidence,
        product_class=product_class,
        category=category,
        liquidity_kind=liquidity_kind,
        all_in_cost=all_in_cost,
        p25_sale_eur=p25_sale_eur,
    )
    gates["PRODUCTION_SOURCE_PASS"] = not sandbox_source
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
    if not book_current:
        money_ready = False
        gates["DATA_PROVENANCE_PASS"] = False
        if "DATA_PROVENANCE_PASS" not in failures:
            failures.append("DATA_PROVENANCE_PASS")
        if action is MoneyReadyDecision.BUY_READY:
            action = MoneyReadyDecision.REVIEW
    why = (
        f"engine={engine.value} money_ready={action.value}. "
        + ("All gates passed." if money_ready else "Failed: " + ", ".join(failures))
    )
    return GateResult(engine, money_ready, action, gates, failures, why)
