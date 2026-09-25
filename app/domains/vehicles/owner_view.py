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
        if quote.get("jurisdiction") == "LIKELY_NI" and quote.get("tax_status") == "UNPROVEN":
            return "NEED TAX PROOF"
        if str(quote.get("bid_label") or "").startswith("ESTIMATED"):
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


def owner_quote(evaluation: dict, *, fx: str = "", registration: str = "", schedule=None) -> dict:
    valuation = evaluation.get("valuation") or {}
    scenarios = build_scenarios(evaluation, registration=registration, fx=fx, schedule=schedule)
    sell = scenarios.get("sell_eur") or valuation.get("conservative_eur")
    status = owner_status(evaluation, quote=scenarios)
    return {
        "status": status,
        "tax_label": PLAIN_JURISDICTION.get(str(scenarios.get("jurisdiction") or ""), "ORIGIN UNKNOWN"),
        "jurisdiction": scenarios.get("jurisdiction"),
        "tax_status": scenarios.get("tax_status"),
        "bid_label": scenarios.get("bid_label") or "ESTIMATED MAX BID",
        "tax_confidence": scenarios.get("tax_confidence"),
        "sell_eur": sell,
        "conservative_eur": valuation.get("conservative_eur"),
        "quick_eur": valuation.get("quick_sale_eur"),
        "max_bid_gbp": scenarios.get("safe_max_bid_gbp"),
        "max_bid_known": bool(scenarios.get("safe_max_bid_gbp")),
        "alt_max_bid_gbp": scenarios.get("alt_max_bid_gbp"),
        "alt_label": scenarios.get("alt_label") or "",
        "alt_vrt_max_bid_gbp": scenarios.get("alt_vrt_max_bid_gbp"),
        "alt_vrt_label": scenarios.get("alt_vrt_label") or "",
        "potential_saving_eur": scenarios.get("potential_saving_eur"),
        "customs_eur": scenarios.get("customs_eur"),
        "import_vat_eur": scenarios.get("import_vat_eur"),
        "vrt_eur": scenarios.get("vrt_eur"),
        "registration_eur": scenarios.get("registration_eur"),
        "transport_eur": scenarios.get("transport_eur"),
        "insurance_eur": scenarios.get("insurance_eur"),
        "repairs_eur": scenarios.get("repairs_eur"),
        "selling_cost_eur": scenarios.get("selling_cost_eur"),
        "auction_charges_eur": scenarios.get("auction_charges_eur"),
        "buyer_premium_eur": scenarios.get("buyer_premium_eur"),
        "premium_vat_eur": scenarios.get("premium_vat_eur"),
        "lot_vat_eur": scenarios.get("lot_vat_eur"),
        "payment_fee_eur": scenarios.get("payment_fee_eur"),
        "hammer_eur": scenarios.get("hammer_eur"),
        "fees_and_tax_eur": scenarios.get("fees_and_tax_eur"),
        "all_in_eur": scenarios.get("all_in_eur"),
        "profit_eur": scenarios.get("profit_eur"),
        "roi": scenarios.get("roi"),
        "lines": scenarios.get("lines") or {},
        "postures": scenarios.get("postures") or {},
        "documents": scenarios.get("documents") or [],
        "taric": scenarios.get("taric") or {},
        "vrt": scenarios.get("vrt") or {},
        "spec": scenarios.get("spec") or {},
        "sources": scenarios.get("sources") or [],
        "scenario_name": scenarios.get("scenario_name") or "",
        "rules_checked": "2026-09-25",
    }
