"""Owner-facing words. Technical states stay available underneath."""

from __future__ import annotations


PLAIN_PROVENANCE = {
    "ROI_NATIVE": "ALREADY IRISH",
    "NI_PRE_2021_PROVEN": "NI TAX FREE — PROVEN",
    "NI_POST_2020_IMPORT_PROVEN": "NI TAX FREE — PROVEN",
    "LIKELY_NI_NEEDS_DOCUMENTS": "NI TAX RELIEF POSSIBLE — NEED DOCUMENTS",
    "GB_ORIGIN": "GB IMPORT TAX APPLIES",
    "GB_TO_NI_UNPROVEN": "GB IMPORT TAX APPLIES",
    "UNKNOWN": "ORIGIN UNKNOWN",
}


def owner_status(evaluation: dict) -> str:
    group = str(evaluation.get("prebid_group") or "")
    economics = evaluation.get("economics") or {}
    if group.startswith("REJECT"):
        return "REJECT"
    if group == "NO_ECONOMIC_HEADROOM":
        return "PRICE TOO HIGH"
    if group == "MARKET_INSUFFICIENT" or not (evaluation.get("valuation") or {}).get("expected_achievable_eur"):
        if group == "MARKET_INSUFFICIENT":
            return "NEED MARKET DATA"
    final = economics.get("final_max_safe_hammer_eur")
    if final:
        return "READY TO BID"
    provenance = str(evaluation.get("provenance_status") or "")
    vrt = str((economics.get("vrt_status") or ""))
    if provenance in {"NI_PRE_2021_PROVEN", "NI_POST_2020_IMPORT_PROVEN", "ROI_NATIVE"} and vrt != "CONFIRMED":
        return "NEED VRT INFO"
    if group in {"ECONOMICALLY_INTERESTING_TAX_DILIGENCE", "POTENTIAL_OPPORTUNITY_TAX_DILIGENCE", "ROBUST_OPPORTUNITY"}:
        return "NEED TAX PROOF"
    return "NEED MARKET DATA"


def plain_provenance(state: str) -> str:
    return PLAIN_PROVENANCE.get(state, "ORIGIN UNKNOWN")


def _gbp(eur: str | None, fx: str) -> str | None:
    if not eur or not fx:
        return None
    from decimal import Decimal

    rate = Decimal(fx)
    if rate <= 0:
        return None
    return str((Decimal(eur) / rate).quantize(Decimal("0.01")))


def owner_quote(evaluation: dict, *, fx: str = "") -> dict:
    """Primary owner numbers. A missing material cost never becomes a bid."""

    valuation = evaluation.get("valuation") or {}
    economics = evaluation.get("economics") or {}
    tax = evaluation.get("tax") or {}
    sell = valuation.get("expected_achievable_eur") or valuation.get("conservative_eur")
    final = economics.get("final_max_safe_hammer_eur")
    ceiling = economics.get("pre_tax_hammer_ceiling_eur")
    status = owner_status(evaluation)
    return {
        "status": status,
        "tax_label": plain_provenance(str(evaluation.get("provenance_status") or "")),
        "sell_eur": sell,
        "conservative_eur": valuation.get("conservative_eur"),
        "quick_eur": valuation.get("quick_sale_eur"),
        "sell_low_eur": valuation.get("expected_achievable_low_eur"),
        "sell_high_eur": valuation.get("expected_achievable_high_eur"),
        "max_bid_gbp": _gbp(final, fx) if final else None,
        "max_bid_known": bool(final),
        "ceiling_before_tax_gbp": None if final else _gbp(ceiling, fx),
        "customs_eur": tax.get("customs_duty_eur"),
        "import_vat_eur": tax.get("import_vat_eur"),
        "vrt_eur": tax.get("vrt_eur"),
        "nox_eur": tax.get("nox_eur"),
        "registration_eur": tax.get("registration_eur"),
        "profit_eur": economics.get("headroom_eur") if final else None,
        "rules_checked": "2026-09-25",
    }
