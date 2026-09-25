"""Owner-facing words. Technical states stay available underneath."""

from __future__ import annotations

from app.domains.vehicles.tax_scenarios import build_scenarios


PLAIN_JURISDICTION = {
    "LIKELY_GB": "GB IMPORT",
    "LIKELY_NI": "LIKELY NORTHERN IRELAND",
    "ROI": "ALREADY IRISH",
    "UNKNOWN": "ORIGIN UNKNOWN",
}


def owner_status(evaluation: dict, *, quote: dict | None = None) -> str:
    group = str(evaluation.get("prebid_group") or "")
    if group.startswith("REJECT"):
        return "REJECT"
    if group == "NO_ECONOMIC_HEADROOM":
        return "PRICE TOO HIGH"
    if group == "MARKET_INSUFFICIENT":
        return "NEED MARKET DATA"
    if quote and quote.get("safe_max_bid_gbp"):
        if quote.get("tax_status") == "UNPROVEN" and quote.get("jurisdiction") == "LIKELY_NI":
            return "NEED TAX PROOF"
        if quote.get("tax_status") == "UNPROVEN":
            return "READY TO BID"
        return "READY TO BID"
    if group in {"ECONOMICALLY_INTERESTING_TAX_DILIGENCE", "POTENTIAL_OPPORTUNITY_TAX_DILIGENCE", "ROBUST_OPPORTUNITY"}:
        return "NEED TAX PROOF"
    return "NEED MARKET DATA"


def plain_provenance(state: str) -> str:
    from app.domains.vehicles.tax_scenarios import jurisdiction_from

    jurisdiction, status = jurisdiction_from("", state)
    if status == "PROVEN" and jurisdiction == "LIKELY_NI":
        return "NI TAX FREE — PROVEN"
    return PLAIN_JURISDICTION.get(jurisdiction, "ORIGIN UNKNOWN")


def owner_quote(evaluation: dict, *, fx: str = "", registration: str = "") -> dict:
    """Primary owner numbers, including conservative tax scenarios."""

    valuation = evaluation.get("valuation") or {}
    scenarios = build_scenarios(evaluation, registration=registration, fx=fx)
    sell = scenarios.get("sell_eur") or valuation.get("conservative_eur")
    status = owner_status(evaluation, quote=scenarios)
    return {
        "status": status,
        "tax_label": PLAIN_JURISDICTION.get(str(scenarios.get("jurisdiction") or ""), "ORIGIN UNKNOWN"),
        "jurisdiction": scenarios.get("jurisdiction"),
        "tax_status": scenarios.get("tax_status"),
        "sell_eur": sell,
        "conservative_eur": valuation.get("conservative_eur"),
        "quick_eur": valuation.get("quick_sale_eur"),
        "max_bid_gbp": scenarios.get("safe_max_bid_gbp"),
        "max_bid_known": bool(scenarios.get("safe_max_bid_gbp")),
        "alt_max_bid_gbp": scenarios.get("alt_max_bid_gbp"),
        "alt_label": scenarios.get("alt_label") or "",
        "potential_saving_eur": scenarios.get("potential_saving_eur"),
        "ceiling_before_tax_gbp": None,
        "customs_eur": scenarios.get("customs_eur"),
        "import_vat_eur": scenarios.get("import_vat_eur"),
        "vrt_eur": scenarios.get("vrt_eur"),
        "registration_eur": scenarios.get("registration_eur"),
        "transport_eur": scenarios.get("transport_eur"),
        "insurance_eur": scenarios.get("insurance_eur"),
        "repairs_eur": scenarios.get("repairs_eur"),
        "fees_and_tax_eur": scenarios.get("fees_and_tax_eur"),
        "profit_eur": scenarios.get("profit_eur"),
        "postures": scenarios.get("postures") or {},
        "documents": scenarios.get("documents") or [],
        "taric": scenarios.get("taric") or {},
        "sources": scenarios.get("sources") or [],
        "scenario_name": scenarios.get("scenario_name") or "",
        "rules_checked": "2026-09-25",
    }
