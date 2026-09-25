"""Stage counts for one auction import. A stage is not a purchase."""

from __future__ import annotations

from app.domains.vehicles.enums import CandidateState
from app.domains.vehicles.evaluate import Evaluation


def funnel_report(evaluations: list[Evaluation]) -> dict[str, object]:
    counts = {
        "entered": len(evaluations),
        "identity_rejects": 0,
        "market_data_rejects": 0,
        "economically_uninteresting": 0,
        "history_or_condition_rejects": 0,
        "provenance_or_tax_blockers": 0,
        "shadow_candidates": 0,
        "other_manual": 0,
    }
    for evaluation in evaluations:
        failures = set(evaluation.gates.failures)
        if evaluation.state is CandidateState.BUY_CANDIDATE:
            counts["shadow_candidates"] += 1
            continue
        if evaluation.state is CandidateState.REJECT:
            counts["identity_rejects"] += 1
        elif evaluation.state is CandidateState.PRICE_TOO_HIGH:
            counts["economically_uninteresting"] += 1
        elif "MARKET_EVIDENCE_PASS" in failures or "VALUATION_CONFIDENCE_PASS" in failures:
            counts["market_data_rejects"] += 1
        elif "PROVENANCE_PASS" in failures or "TAX_MODEL_PASS" in failures or "VRT_MODEL_PASS" in failures:
            counts["provenance_or_tax_blockers"] += 1
        elif "HISTORY" in " ".join(failures) or "CONDITION_PASS" in failures:
            counts["history_or_condition_rejects"] += 1
        else:
            counts["other_manual"] += 1
    return counts
