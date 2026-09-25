"""Owner tax scenarios. Estimates stay labelled. Proven relief stays gated."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.money import money
from app.domains.vehicles.enums import RegistrationSignal
from app.domains.vehicles.identity import registration_signal
from app.domains.vehicles.policy import REQUIRED_ABSOLUTE_PROFIT_EUR, UNKNOWN_MECHANICAL_EXPECTED_EUR
from app.domains.vehicles.tax import REVENUE_APPLYING_TAX, REVENUE_NI, REVENUE_VAT_RATES, VAT_RATE

TARIC_CANDIDATE_USED_DIESEL_LE_5T_LE_2500 = "87042199"
TARIC_THIRD_COUNTRY_DUTY = Decimal("0.10")
TARIC_SOURCE = "https://ec.europa.eu/taxation_customs/dds2/taric/measures.jsp?Lang=en&Taric=87042199"
TARIC_CHECKED = "2026-09-25"
TRANSPORT_ESTIMATE_EUR = Decimal("350")
INSURANCE_ESTIMATE_EUR = Decimal("80")
REGISTRATION_ESTIMATE_EUR = Decimal("100")
VRT_PANEL_ESTIMATE_EUR = Decimal("200")


@dataclass(frozen=True, slots=True)
class TaxScenario:
    name: str
    hammer_eur: Decimal | None
    customs_eur: Decimal | None
    import_vat_eur: Decimal | None
    vrt_eur: Decimal | None
    registration_eur: Decimal | None
    transport_eur: Decimal | None
    insurance_eur: Decimal | None
    repairs_eur: Decimal | None
    fees_and_tax_eur: Decimal | None
    profit_eur: Decimal | None
    posture: str
    notes: tuple[str, ...]


def jurisdiction_from(registration: str | None, provenance: str) -> tuple[str, str]:
    """Likely jurisdiction and whether NI/GB preferential status is proven."""

    if provenance == "ROI_NATIVE":
        return "ROI", "PROVEN"
    if provenance in {"NI_PRE_2021_PROVEN", "NI_POST_2020_IMPORT_PROVEN"}:
        return "LIKELY_NI", "PROVEN"
    signal = registration_signal(registration)
    if signal is RegistrationSignal.NI_FORMAT_WEAK or provenance == "LIKELY_NI_NEEDS_DOCUMENTS":
        return "LIKELY_NI", "UNPROVEN"
    if signal is RegistrationSignal.GB_FORMAT or provenance in {"GB_ORIGIN", "GB_TO_NI_UNPROVEN"}:
        return "LIKELY_GB", "UNPROVEN"
    if signal is RegistrationSignal.IE_FORMAT:
        return "ROI", "UNPROVEN"
    return "UNKNOWN", "UNPROVEN"


def candidate_taric(*, fuel: str = "diesel", used: bool = True, gvw_tonnes: Decimal | None = None, engine_cc: int | None = None) -> dict:
    """Candidate CN for ordinary used diesel panel vans. Not a legal declaration."""

    gvw = gvw_tonnes or Decimal("3.5")
    if fuel.lower() == "electric":
        return {
            "candidate_taric_code": "870460",
            "third_country_duty_rate": None,
            "source": TARIC_SOURCE,
            "effective_date": "1999-01-01",
            "classification_confidence": "LOW",
            "label": "ESTIMATED TARIFF CLASSIFICATION",
            "note": "Electric goods vehicle. Confirm the exact TARIC leaf before filing.",
        }
    if used and gvw <= 5 and (engine_cc is None or engine_cc <= 2500):
        return {
            "candidate_taric_code": TARIC_CANDIDATE_USED_DIESEL_LE_5T_LE_2500,
            "third_country_duty_rate": str(TARIC_THIRD_COUNTRY_DUTY),
            "source": TARIC_SOURCE,
            "effective_date": "1999-01-01",
            "classification_confidence": "MEDIUM",
            "label": "ESTIMATED TARIFF CLASSIFICATION",
            "note": "Used diesel goods vehicle, GVW ≤ 5 t, engine ≤ 2 500 cm³. Official third-country duty 10%.",
        }
    if used and gvw <= 5:
        return {
            "candidate_taric_code": "87042139",
            "third_country_duty_rate": "0.22",
            "source": "https://ec.europa.eu/taxation_customs/dds2/taric/measures.jsp?Lang=en&Taric=87042139",
            "effective_date": "1999-01-01",
            "classification_confidence": "MEDIUM",
            "label": "ESTIMATED TARIFF CLASSIFICATION",
            "note": "Used diesel goods vehicle, GVW ≤ 5 t, engine > 2 500 cm³. Official third-country duty 22%.",
        }
    return {
        "candidate_taric_code": "",
        "third_country_duty_rate": None,
        "source": TARIC_SOURCE,
        "effective_date": "",
        "classification_confidence": "LOW",
        "label": "ESTIMATED TARIFF CLASSIFICATION",
        "note": "Not enough characteristics for a candidate leaf.",
    }


def _stack(
    *,
    hammer: Decimal,
    duty_rate: Decimal,
    vrt: Decimal,
    registration: Decimal,
    transport: Decimal,
    insurance: Decimal,
    repairs: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    customs_value = hammer + transport + insurance
    duty = money(customs_value * duty_rate)
    import_vat = money((customs_value + duty) * VAT_RATE)
    fees = money(duty + import_vat + vrt + registration + transport + insurance + repairs)
    return duty, import_vat, fees


def _solve_hammer(
    *,
    ceiling: Decimal,
    duty_rate: Decimal,
    vrt: Decimal,
    registration: Decimal,
    transport: Decimal,
    insurance: Decimal,
) -> Decimal | None:
    """Ceiling already nets auction fees, selling friction, and the required profit screen."""

    fixed = vrt + registration + transport + insurance
    # H = ceiling - duty - import_vat - fixed
    # duty = r * (H + T + I)
    # import_vat = 0.23 * (H + T + I) * (1 + r)
    factor = duty_rate + VAT_RATE * (Decimal("1") + duty_rate)
    border = transport + insurance
    numerator = ceiling - fixed - money(factor * border)
    denom = Decimal("1") + factor
    if denom <= 0:
        return None
    hammer = money(numerator / denom)
    return hammer if hammer > 0 else None


def build_scenarios(evaluation: dict, *, registration: str = "", fx: str = "") -> dict:
    valuation = evaluation.get("valuation") or {}
    economics = evaluation.get("economics") or {}
    provenance = str(evaluation.get("provenance_status") or "")
    sell = valuation.get("expected_achievable_eur") or valuation.get("conservative_eur")
    ceiling = economics.get("pre_tax_hammer_ceiling_eur") or valuation.get("max_hammer_vat_stress_eur")
    jurisdiction, tax_status = jurisdiction_from(registration, provenance)
    taric = candidate_taric()
    duty_rate = Decimal(str(taric["third_country_duty_rate"] or "0"))
    vrt = VRT_PANEL_ESTIMATE_EUR
    repairs = UNKNOWN_MECHANICAL_EXPECTED_EUR
    transport = TRANSPORT_ESTIMATE_EUR
    insurance = INSURANCE_ESTIMATE_EUR
    registration_fee = REGISTRATION_ESTIMATE_EUR

    if not sell or not ceiling:
        return {
            "jurisdiction": jurisdiction,
            "tax_status": tax_status,
            "safe_max_bid_gbp": None,
            "alt_max_bid_gbp": None,
            "alt_label": "",
            "sell_eur": sell,
            "fees_and_tax_eur": None,
            "profit_eur": None,
            "customs_eur": None,
            "import_vat_eur": None,
            "vrt_eur": None,
            "taric": taric,
            "postures": {},
            "documents": _documents(jurisdiction, tax_status),
            "sources": _sources(),
        }

    sell_d = Decimal(str(sell))
    ceiling_d = Decimal(str(ceiling))

    gb = _scenario("GB_STANDARD", ceiling_d, duty_rate, vrt, registration_fee, transport, insurance, repairs, sell_d)
    ni = _scenario("NI_ACCEPTED", ceiling_d, Decimal("0"), vrt, registration_fee, transport, insurance, repairs, sell_d)
    uk = _scenario("UK_ORIGIN", ceiling_d, Decimal("0"), vrt, registration_fee, transport, insurance, repairs, sell_d)

    if tax_status == "PROVEN" and jurisdiction == "LIKELY_NI":
        safe, alt, alt_label = ni, None, ""
    elif jurisdiction == "LIKELY_NI":
        safe, alt, alt_label = gb, ni, "MAX BID IF NI STATUS PROVEN"
    elif jurisdiction == "LIKELY_GB":
        safe, alt, alt_label = gb, uk, "MAX BID IF UK ORIGIN PROVEN"
    elif jurisdiction == "ROI":
        safe = _scenario("ROI", ceiling_d, Decimal("0"), Decimal("0"), Decimal("0"), transport, insurance, repairs, sell_d)
        alt, alt_label = None, ""
    else:
        safe, alt, alt_label = gb, None, ""

    return {
        "jurisdiction": jurisdiction,
        "tax_status": tax_status,
        "safe_max_bid_gbp": _gbp(safe.hammer_eur, fx) if safe and safe.hammer_eur else None,
        "safe_max_bid_eur": str(safe.hammer_eur) if safe and safe.hammer_eur else None,
        "alt_max_bid_gbp": _gbp(alt.hammer_eur, fx) if alt and alt.hammer_eur else None,
        "alt_label": alt_label,
        "potential_saving_eur": str(money(alt.hammer_eur - safe.hammer_eur)) if alt and alt.hammer_eur and safe and safe.hammer_eur else None,
        "sell_eur": sell,
        "fees_and_tax_eur": str(safe.fees_and_tax_eur) if safe else None,
        "profit_eur": str(safe.profit_eur) if safe else None,
        "customs_eur": str(safe.customs_eur) if safe else None,
        "import_vat_eur": str(safe.import_vat_eur) if safe else None,
        "vrt_eur": str(safe.vrt_eur) if safe else None,
        "registration_eur": str(safe.registration_eur) if safe else None,
        "transport_eur": str(safe.transport_eur) if safe else None,
        "insurance_eur": str(safe.insurance_eur) if safe else None,
        "repairs_eur": str(safe.repairs_eur) if safe else None,
        "taric": taric,
        "postures": {
            "customs": "ESTIMATED" if safe and safe.customs_eur and safe.customs_eur > 0 else ("CALCULATED" if safe and safe.customs_eur == 0 else "UNKNOWN"),
            "import_vat": "CALCULATED" if safe and safe.import_vat_eur is not None else "UNKNOWN",
            "vrt": "ESTIMATED",
            "ni_relief": "PROVEN" if tax_status == "PROVEN" and jurisdiction == "LIKELY_NI" else "NOT PROVEN",
        },
        "documents": _documents(jurisdiction, tax_status),
        "sources": _sources(),
        "scenario_name": safe.name if safe else "",
        "required_profit_eur": str(REQUIRED_ABSOLUTE_PROFIT_EUR),
    }


def _scenario(
    name: str,
    ceiling: Decimal,
    duty_rate: Decimal,
    vrt: Decimal,
    registration: Decimal,
    transport: Decimal,
    insurance: Decimal,
    repairs: Decimal,
    sell: Decimal,
) -> TaxScenario:
    hammer = _solve_hammer(ceiling=ceiling, duty_rate=duty_rate, vrt=vrt, registration=registration, transport=transport, insurance=insurance)
    if hammer is None:
        return TaxScenario(name, None, None, None, vrt, registration, transport, insurance, repairs, None, None, "ESTIMATED", ("Could not solve a positive hammer.",))
    duty, import_vat, fees = _stack(hammer=hammer, duty_rate=duty_rate, vrt=vrt, registration=registration, transport=transport, insurance=insurance, repairs=repairs)
    # Auction fees already sit inside the ceiling. Surface the tax/logistics stack for the owner.
    profit = money(sell - (hammer + fees) - REQUIRED_ABSOLUTE_PROFIT_EUR + REQUIRED_ABSOLUTE_PROFIT_EUR)
    # Profit at this hammer is approximately the required profit screen remaining after costs.
    # Use sell - hammer - fees as the owner-facing estimated profit.
    profit = money(sell - hammer - fees)
    return TaxScenario(
        name=name,
        hammer_eur=hammer,
        customs_eur=duty,
        import_vat_eur=import_vat,
        vrt_eur=vrt,
        registration_eur=registration,
        transport_eur=transport,
        insurance_eur=insurance,
        repairs_eur=repairs,
        fees_and_tax_eur=fees,
        profit_eur=profit,
        posture="ESTIMATED",
        notes=(
            f"TARIC candidate {TARIC_CANDIDATE_USED_DIESEL_LE_5T_LE_2500} at {duty_rate * 100}% third-country duty." if duty_rate else "No customs duty in this scenario.",
            "VRT €200 is an estimate for a typical N1 panel van. Homologation still required.",
            f"Import VAT uses Revenue standard rate {VAT_RATE * 100}%.",
        ),
    )


def _gbp(eur: Decimal | None, fx: str) -> str | None:
    if eur is None or not fx:
        return None
    rate = Decimal(fx)
    if rate <= 0:
        return None
    return str((eur / rate).quantize(Decimal("0.01")))


def _documents(jurisdiction: str, tax_status: str) -> list[str]:
    if tax_status == "PROVEN":
        return []
    if jurisdiction == "LIKELY_NI":
        return [
            "NI import declaration tied to the VIN",
            "or original V5C (NI keeper) + NI service history + NI MOT history",
            "CoC / mass / seats for VRT",
        ]
    if jurisdiction == "LIKELY_GB":
        return ["UK preferential origin statement if claiming 0% duty", "CoC / mass / seats for VRT", "Confirmed transport and insurance invoices"]
    return ["Origin evidence", "CoC / mass / seats for VRT"]


def _sources() -> list[dict[str, str]]:
    return [
        {"id": "taric", "url": TARIC_SOURCE, "checked": TARIC_CHECKED, "note": "EU TARIC third-country duty for 87042199"},
        {"id": "ni", "url": REVENUE_NI, "checked": TARIC_CHECKED, "note": "NI customs duty and import VAT relief"},
        {"id": "vat", "url": REVENUE_VAT_RATES, "checked": TARIC_CHECKED, "note": "Standard VAT 23%"},
        {"id": "vrt", "url": REVENUE_APPLYING_TAX, "checked": TARIC_CHECKED, "note": "Category B and €200 N1 VRT"},
    ]
