"""Labels for the owner. None of these pass a due-diligence gate."""

from __future__ import annotations

from decimal import Decimal


def catalogue_hard_reject(*, title: str = "", hint: str = "", write_off_label: str = "") -> str:
    """Owner-facing hard stop. Economics must not override it."""

    text = f"{hint} {title} {write_off_label}".upper().replace("-", " ").replace("_", " ")
    if "NON RUNNER" in text:
        return "REJECT_NON_RUNNER"
    for label in ("CAT A", "CAT B", "CAT S"):
        if label in text:
            return f"REJECT_WRITE_OFF_{label.replace(' ', '_')}"
    return ""


def prebid_economic_group(valuation: object, *, hard_reject: str = "") -> str:
    """Pre-bid economic screen. This is not BUY_READY."""

    if hard_reject:
        return hard_reject
    floor = bool(getattr(valuation, "prebid_floor_available", False))
    market = getattr(valuation, "market_floor_confidence", "")
    stress = getattr(valuation, "max_hammer_vat_stress_eur", None)
    market_hammer = getattr(valuation, "max_hammer_market_floor_eur", None)
    if not floor:
        return "MARKET_INSUFFICIENT"
    final_safe = getattr(valuation, "final_max_safe_hammer_eur", None)
    if market in {"HIGH", "MEDIUM"} and final_safe is not None and final_safe > 0:
        return "ROBUST_OPPORTUNITY"
    if final_safe == 0 or stress == 0 or market_hammer == 0:
        return "NO_ECONOMIC_HEADROOM"
    if stress is not None or market_hammer is not None:
        return "ECONOMICALLY_INTERESTING_TAX_DILIGENCE"
    return "MARKET_INSUFFICIENT"


def economic_label(
    *,
    state: str,
    market_pass: bool,
    auction_cost_pass: bool,
    has_conservative: bool,
    preliminary_economics: bool = False,
) -> str:
    if state == "BUY_CANDIDATE":
        return "SHADOW_CANDIDATE"
    if state == "PRICE_TOO_HIGH" or (has_conservative and state == "REJECT"):
        return "NOT_ECONOMIC"
    if market_pass and has_conservative and state == "MANUAL_EVIDENCE_REQUIRED" and (auction_cost_pass or preliminary_economics):
        return "ECONOMICALLY_INTERESTING_PENDING_DILIGENCE"
    if not has_conservative:
        return "INSUFFICIENT_MARKET"
    return "NOT_A_CANDIDATE"


def ni_landing_scenarios(
    provenance_state: str,
    *,
    conservative_resale_eur: object = None,
    scenario_landed_eur: dict[str, object] | None = None,
) -> dict[str, object]:
    """Show NI cost scenarios. survives is an economic comparison, never a gate pass."""

    unresolved = provenance_state in {"UNKNOWN", "LIKELY_NI_NEEDS_DOCUMENTS", "GB_TO_NI_UNPROVEN"}
    landed = scenario_landed_eur or {}
    names = (
        ("SCENARIO_A", "qualifying NI treatment"),
        ("SCENARIO_B", "import VAT or customs exposure"),
        ("SCENARIO_C", "VRT uncertainty"),
    )
    scenarios = []
    compared = 0
    survivors = 0
    for name, treatment in names:
        cost = landed.get(name)
        survives = None
        if conservative_resale_eur is not None and cost is not None:
            compared += 1
            survives = cost < conservative_resale_eur
            survivors += int(bool(survives))
        scenarios.append(
            {
                "name": name,
                "treatment": treatment,
                "landed_eur": None if cost is None else str(cost),
                "survives_conservative_resale": survives,
                "passes_gate": False,
            }
        )
    if unresolved and compared == 0:
        classification = "DOCUMENT_DEPENDENT"
    elif compared and survivors == compared:
        classification = "ROBUST_OPPORTUNITY"
    elif compared and survivors == 0:
        classification = "NOT_ECONOMIC"
    elif compared:
        classification = "DOCUMENT_DEPENDENT"
    else:
        classification = "USE_GATES"
    return {
        "landing_cost": "LANDING_COST_UNRESOLVED" if unresolved else "SEE_TAX_MODEL",
        "classification": classification,
        "gate_pass": False,
        "scenarios": scenarios,
    }


def vat_decision(
    *,
    all_in_eur: Decimal,
    pessimistic_resale_eur: Decimal,
    optimistic_resale_eur: Decimal,
    required_profit_eur: Decimal = Decimal("1500"),
) -> dict[str, object]:
    """VAT uncertainty blocks a buy. It blocks a preliminary look only when the scenarios disagree."""

    pessimistic_ok = pessimistic_resale_eur - all_in_eur >= required_profit_eur
    optimistic_ok = optimistic_resale_eur - all_in_eur >= required_profit_eur
    if pessimistic_ok and optimistic_ok:
        label = "ECONOMICALLY_INTERESTING_PENDING_DILIGENCE"
    elif pessimistic_ok or optimistic_ok:
        label = "VALUATION_UNRESOLVED"
    else:
        label = "NOT_ECONOMIC"
    return {"label": label, "buy_candidate": False, "gate_pass": False}
