"""Fail-closed candidate gates. Unknown does not pass."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.domains.vehicles.enums import CandidateState, CommercialClass, LiquidityClass, ProvenanceState, VrtState
from app.domains.vehicles.history import HistoryAssessment
from app.domains.vehicles.enums import CheckOutcome
from app.domains.vehicles.policy import MIN_CLOSE_COMPS, MIN_ELIGIBLE_COMPS, VALUATION_CONFIDENCE_MIN
from app.domains.vehicles.provenance import ProvenanceResult
from app.domains.vehicles.tax import TaxPosition
from app.domains.vehicles.valuation import ValuationResult

GATES = (
    "IDENTITY_PASS",
    "COMMERCIAL_CLASS_PASS",
    "HISTORY_PASS",
    "MILEAGE_PASS",
    "PROVENANCE_PASS",
    "TAX_MODEL_PASS",
    "VRT_MODEL_PASS",
    "AUCTION_COST_PASS",
    "MARKET_EVIDENCE_PASS",
    "VALUATION_CONFIDENCE_PASS",
    "LIQUIDITY_PASS",
    "CONDITION_PASS",
    "RECONDITIONING_PASS",
    "DOWNSIDE_PASS",
    "PROFIT_PASS",
    "DATA_FRESHNESS_PASS",
    "PRICE_PASS",
)


@dataclass(slots=True)
class GateReport:
    gates: dict[str, bool]
    failures: list[str] = field(default_factory=list)
    state: CandidateState = CandidateState.INSUFFICIENT_DATA

    def to_dict(self) -> dict[str, object]:
        return {
            "gates": dict(self.gates),
            "failures": list(self.failures),
            "state": self.state.value,
        }


def decide_gates(
    *,
    identity_ok: bool,
    commercial_class: CommercialClass,
    history: HistoryAssessment,
    provenance: ProvenanceResult,
    tax: TaxPosition,
    auction_blocked: bool,
    valuation: ValuationResult,
    condition_ok: bool,
    reconditioning_ok: bool,
    downside_ok: bool,
    profit_ok: bool,
    fresh_ok: bool,
    price_ok: bool,
    hard_reject: bool,
    economics_blocked: bool,
) -> GateReport:
    market_ok = (
        valuation.fresh
        and valuation.comparable_count >= MIN_ELIGIBLE_COMPS
        and valuation.close_count >= MIN_CLOSE_COMPS
    )
    gates = {
        "IDENTITY_PASS": identity_ok,
        "COMMERCIAL_CLASS_PASS": commercial_class is CommercialClass.N1_GOODS,
        "HISTORY_PASS": not history.blocking_failure and history.stolen.outcome is CheckOutcome.CLEAR and history.finance.outcome is CheckOutcome.CLEAR and history.write_off.outcome is CheckOutcome.CLEAR,
        "MILEAGE_PASS": history.mileage.outcome is CheckOutcome.CLEAR,
        "PROVENANCE_PASS": provenance.state
        in {
            ProvenanceState.ROI_NATIVE,
            ProvenanceState.NI_PRE_2021_PROVEN,
            ProvenanceState.NI_POST_2020_IMPORT_PROVEN,
            ProvenanceState.GB_ORIGIN,
        },
        "TAX_MODEL_PASS": not tax.blocked,
        "VRT_MODEL_PASS": tax.vrt_state is VrtState.VRT_CONFIRMED and tax.vrt_eur is not None,
        "AUCTION_COST_PASS": not auction_blocked,
        "MARKET_EVIDENCE_PASS": market_ok,
        "VALUATION_CONFIDENCE_PASS": valuation.confidence >= VALUATION_CONFIDENCE_MIN and valuation.expected_achievable_eur is not None,
        "LIQUIDITY_PASS": valuation.liquidity.classification in {LiquidityClass.DEEP, LiquidityClass.ADEQUATE},
        "CONDITION_PASS": condition_ok,
        "RECONDITIONING_PASS": reconditioning_ok,
        "DOWNSIDE_PASS": downside_ok,
        "PROFIT_PASS": profit_ok,
        "DATA_FRESHNESS_PASS": fresh_ok,
        "PRICE_PASS": price_ok,
    }
    failures = [name for name, passed in gates.items() if not passed]
    evidence_names = [name for name in failures if name != "PRICE_PASS"]
    if hard_reject:
        state = CandidateState.REJECT
    elif not identity_ok and commercial_class is CommercialClass.UNKNOWN and valuation.comparable_count == 0:
        state = CandidateState.INSUFFICIENT_DATA
    elif not failures:
        state = CandidateState.BUY_CANDIDATE
    elif not evidence_names and not price_ok and not economics_blocked:
        state = CandidateState.PRICE_TOO_HIGH
    elif commercial_class is CommercialClass.UNKNOWN and not identity_ok:
        state = CandidateState.INSUFFICIENT_DATA
    else:
        state = CandidateState.MANUAL_EVIDENCE_REQUIRED
    if commercial_class in {CommercialClass.PASSENGER, CommercialClass.PARTS_OR_NOT_A_VEHICLE}:
        state = CandidateState.REJECT
    return GateReport(gates=gates, failures=failures, state=state)
