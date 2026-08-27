"""Commercial ranking. Fake asking spreads cannot outrank realised evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.money import ZERO, money
from app.models.enums import IdentityLevel, MoneyReadyDecision

RANK_BUY_READY = "BUY_READY"
RANK_WATCH_HIGH_EVIDENCE = "WATCH_HIGH_EVIDENCE"
RANK_REVIEW_INTERESTING = "REVIEW_INTERESTING"
RANK_UNVALUED = "UNVALUED"
RANK_REJECTED = "REJECTED"

GROUP_ORDER = {
    RANK_BUY_READY: 1,
    RANK_WATCH_HIGH_EVIDENCE: 2,
    RANK_REVIEW_INTERESTING: 3,
    RANK_UNVALUED: 4,
    RANK_REJECTED: 5,
}

UNVALIDATED_VALUE = "UNVALIDATED_VALUE"
VALIDATED_VALUE = "VALIDATED_VALUE"


@dataclass(slots=True)
class RankResult:
    group: str
    group_order: int
    score: Decimal
    value_status: str
    notes: list[str]


def _clip(value: Decimal) -> Decimal:
    if value < ZERO:
        return ZERO
    if value > Decimal("1"):
        return Decimal("1")
    return value


def commercial_rank(
    *,
    money_ready_decision: str | MoneyReadyDecision,
    engine_decision: str = "",
    identity_level: IdentityLevel | str = IdentityLevel.UNKNOWN,
    identity_confidence: Decimal = ZERO,
    product_class: str = "primary",
    realised_count: int = 0,
    binding_count: int = 0,
    expected_profit: Decimal = ZERO,
    valuation_confidence: Decimal = ZERO,
    liquidity_score: Decimal = ZERO,
    downside_profit: Decimal = ZERO,
    failed_gates: list[str] | None = None,
) -> RankResult:
    money_dec = money_ready_decision.value if isinstance(money_ready_decision, MoneyReadyDecision) else str(
        money_ready_decision or ""
    )
    ident = identity_level.value if isinstance(identity_level, IdentityLevel) else str(identity_level or "unknown")
    accessory = product_class in {"accessory", "game", "consumable"}
    notes: list[str] = []
    has_binding = (realised_count + binding_count) > 0
    value_status = VALIDATED_VALUE if has_binding else UNVALIDATED_VALUE
    if not has_binding:
        notes.append("UNVALIDATED_VALUE: no realised or binding evidence.")

    if accessory or ident in {"unknown", "category"} or money_dec == "IGNORE" or engine_decision == "IGNORE":
        notes.append("Rejected: accessory, weak identity, or ignore.")
        return RankResult(RANK_REJECTED, GROUP_ORDER[RANK_REJECTED], ZERO, value_status, notes)

    if money_dec == "BUY_READY":
        downside_safety = _clip((downside_profit + Decimal("50")) / Decimal("200"))
        score = money(
            max(expected_profit, ZERO)
            * max(valuation_confidence, ZERO)
            * max(liquidity_score, Decimal("0.10"))
            * max(downside_safety, Decimal("0.10"))
        )
        return RankResult(RANK_BUY_READY, GROUP_ORDER[RANK_BUY_READY], score, value_status, notes)

    strong_id = ident in {"exact", "variant"} and identity_confidence >= Decimal("0.80")
    if money_dec == "WATCH" and has_binding and strong_id:
        score = money(max(expected_profit, ZERO) * valuation_confidence * Decimal("0.5"))
        return RankResult(
            RANK_WATCH_HIGH_EVIDENCE, GROUP_ORDER[RANK_WATCH_HIGH_EVIDENCE], score, value_status, notes
        )

    failures = failed_gates or []
    evidence_failed = "PRICE_EVIDENCE_PASS" in failures
    if strong_id and has_binding and not evidence_failed:
        score = money(max(expected_profit, ZERO) * Decimal("0.25"))
        return RankResult(
            RANK_REVIEW_INTERESTING, GROUP_ORDER[RANK_REVIEW_INTERESTING], score, value_status, notes
        )

    if not has_binding:
        return RankResult(RANK_UNVALUED, GROUP_ORDER[RANK_UNVALUED], ZERO, UNVALIDATED_VALUE, notes)

    score = money(max(expected_profit, ZERO) * Decimal("0.10"))
    return RankResult(RANK_REVIEW_INTERESTING, GROUP_ORDER[RANK_REVIEW_INTERESTING], score, value_status, notes)
