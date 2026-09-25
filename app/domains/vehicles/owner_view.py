"""Owner-facing words. Technical states stay available underneath."""

from __future__ import annotations


PLAIN_PROVENANCE = {
    "ROI_NATIVE": "Already Irish registered",
    "NI_PRE_2021_PROVEN": "NI customs status proven",
    "NI_POST_2020_IMPORT_PROVEN": "NI import declaration proven",
    "LIKELY_NI_NEEDS_DOCUMENTS": "NI history possible — documents needed",
    "GB_ORIGIN": "Great Britain origin — import costs apply",
    "GB_TO_NI_UNPROVEN": "Seen in NI — customs clearance not proven",
    "UNKNOWN": "Origin not established",
}


def owner_status(evaluation: dict) -> str:
    group = str(evaluation.get("prebid_group") or "")
    if group.startswith("REJECT"):
        return "HARD REJECT"
    if evaluation.get("buy_ready"):
        return "BUY READY"
    if group == "NO_ECONOMIC_HEADROOM":
        return "PRICE TOO HIGH"
    if group == "MARKET_INSUFFICIENT":
        return "MARKET INSUFFICIENT"
    if group in {"ECONOMICALLY_INTERESTING_TAX_DILIGENCE", "POTENTIAL_OPPORTUNITY_TAX_DILIGENCE"}:
        return "TAX DILIGENCE"
    if group == "ROBUST_OPPORTUNITY":
        return "MARKET READY"
    return "MARKET INSUFFICIENT"


def plain_provenance(state: str) -> str:
    return PLAIN_PROVENANCE.get(state, state.replace("_", " ").title())
