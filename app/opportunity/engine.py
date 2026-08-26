"""Transparent opportunity scoring and BUY/WATCH/IGNORE/REVIEW decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.core.money import ZERO, money
from app.models.enums import Decision, IdentityLevel


@dataclass(slots=True)
class ScoreBreakdown:
    profit: Decimal
    roi: Decimal
    speed: Decimal
    confidence: Decimal
    liquidity: Decimal
    downside: Decimal
    data_quality: Decimal
    urgency: Decimal
    risk_penalty: Decimal
    total: Decimal
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OpportunityDecision:
    decision: Decision
    score: Decimal
    breakdown: ScoreBreakdown
    why: str


def _clip(value: Decimal) -> Decimal:
    if value < ZERO:
        return ZERO
    if value > Decimal("1"):
        return Decimal("1")
    return value


def score_opportunity(
    *,
    expected_profit: Decimal,
    roi: Decimal,
    expected_days: int | None,
    valuation_confidence: Decimal,
    identity_confidence: Decimal,
    condition_confidence: Decimal,
    liquidity_score: Decimal,
    downside_profit: Decimal,
    risk_score: Decimal,
    identity_level: IdentityLevel,
    ends_in_hours: float | None,
    min_profit: Decimal,
    min_roi: Decimal,
    min_confidence: Decimal,
    max_days: int,
    max_capital: Decimal,
    capital_required: Decimal,
    asking: Decimal | None,
    max_buy: Decimal,
) -> OpportunityDecision:
    notes: list[str] = []
    profit_s = _clip(expected_profit / Decimal("250"))
    roi_s = _clip(roi / Decimal("0.6"))
    if valuation_confidence < min_confidence:
        # Do not let unvalued accessories outrank real inventory on fake Reverb comps.
        profit_s = ZERO
        roi_s = ZERO
        notes.append("Profit/ROI score zeroed: valuation confidence below minimum.")
    speed_s = Decimal("0.4") if expected_days is None else _clip(Decimal(str(max_days - expected_days)) / Decimal(str(max_days)))
    conf_s = money((valuation_confidence + identity_confidence + condition_confidence) / Decimal("3"))
    liq_s = liquidity_score
    down_s = _clip((downside_profit + Decimal("50")) / Decimal("200"))
    data_s = conf_s
    urgency_s = Decimal("0")
    if ends_in_hours is not None and ends_in_hours <= 12:
        urgency_s = Decimal("0.8")
        notes.append("Auction/listing ends within 12 hours.")
    risk_pen = risk_score
    total = money(
        profit_s * Decimal("0.22")
        + roi_s * Decimal("0.16")
        + speed_s * Decimal("0.10")
        + conf_s * Decimal("0.16")
        + liq_s * Decimal("0.10")
        + down_s * Decimal("0.10")
        + data_s * Decimal("0.08")
        + urgency_s * Decimal("0.04")
        - risk_pen * Decimal("0.16")
    )
    breakdown = ScoreBreakdown(
        profit=profit_s,
        roi=roi_s,
        speed=speed_s,
        confidence=conf_s,
        liquidity=liq_s,
        downside=down_s,
        data_quality=data_s,
        urgency=urgency_s,
        risk_penalty=risk_pen,
        total=total,
        notes=notes,
    )

    reasons: list[str] = []
    if identity_level in {IdentityLevel.UNKNOWN, IdentityLevel.CATEGORY} or identity_confidence < Decimal("0.45"):
        reasons.append("Identity is too weak to buy without human review.")
        return OpportunityDecision(Decision.REVIEW, total, breakdown, " ".join(reasons))
    if valuation_confidence < min_confidence:
        reasons.append(f"Valuation confidence {valuation_confidence} is below minimum {min_confidence}.")
        return OpportunityDecision(Decision.REVIEW, total, breakdown, " ".join(reasons))
    if capital_required > max_capital:
        reasons.append("Capital required exceeds max capital per item.")
        return OpportunityDecision(Decision.IGNORE, total, breakdown, " ".join(reasons))
    if expected_profit < ZERO:
        reasons.append("Expected profit after all modelled costs is negative.")
        return OpportunityDecision(Decision.IGNORE, total, breakdown, " ".join(reasons))
    days_ok = expected_days is None or expected_days <= max_days
    under_max = asking is None or asking <= max_buy
    if (
        expected_profit >= min_profit
        and roi >= min_roi
        and valuation_confidence >= min_confidence
        and days_ok
        and under_max
        and downside_profit >= ZERO
        and risk_score < Decimal("0.55")
    ):
        why = (
            f"BUY: expected profit €{expected_profit} at ROI {roi} after all modelled costs. "
            f"Ask is at or below max buy €{max_buy}. Downside case still non-negative. "
            f"Identity {identity_level.value}, valuation confidence {valuation_confidence}."
        )
        return OpportunityDecision(Decision.BUY, total, breakdown, why)
    if expected_profit >= min_profit * Decimal("0.5") and roi >= min_roi * Decimal("0.5"):
        why = (
            f"WATCH: economics are interesting but fail a BUY gate "
            f"(profit €{expected_profit}, ROI {roi}, confidence {valuation_confidence}, "
            f"days {expected_days}, under_max={under_max})."
        )
        return OpportunityDecision(Decision.WATCH, total, breakdown, why)
    return OpportunityDecision(
        Decision.IGNORE,
        total,
        breakdown,
        f"IGNORE: expected profit €{expected_profit} / ROI {roi} does not clear configured thresholds.",
    )
