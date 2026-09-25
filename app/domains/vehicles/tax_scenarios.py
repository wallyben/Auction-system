"""Owner money scenarios. Safe max bid uses a full all-in stack and conservative tax."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from app.core.config import settings
from app.core.money import ZERO, money, money_down
from app.domains.vehicles.auction_costs import AuctionFeeSchedule, PremiumBand, auction_costs
from app.domains.vehicles.enums import AuctionVatTreatment, EvidencePosture, Fuel, RegistrationSignal
from app.domains.vehicles.identity import registration_signal
from app.domains.vehicles.max_bid import profit_at, roi_at
from app.domains.vehicles.policy import (
    REQUIRED_ABSOLUTE_PROFIT_EUR,
    REQUIRED_ROI,
    SELLING_FRICTION_FLOOR_EUR,
    SELLING_FRICTION_RATE,
    UNKNOWN_MECHANICAL_EXPECTED_EUR,
)
from app.domains.vehicles.tax import (
    REVENUE_APPLYING_TAX,
    REVENUE_NI,
    REVENUE_VAT_RATES,
    VAT_RATE,
    _flat_200_ratio,
    category_b_co2_charge,
)

TARIC_SOURCE_87042199 = "https://ec.europa.eu/taxation_customs/dds2/taric/measures.jsp?Lang=en&Taric=87042199"
TARIC_SOURCE_87042139 = "https://ec.europa.eu/taxation_customs/dds2/taric/measures.jsp?Lang=en&Taric=87042139"
TARIC_CHECKED = "2026-09-25"
TRANSPORT_ESTIMATE_EUR = Decimal("350")
INSURANCE_ESTIMATE_EUR = Decimal("80")
REGISTRATION_ESTIMATE_EUR = Decimal("100")
VRT_200 = Decimal("200")


@dataclass(frozen=True, slots=True)
class VehicleSpec:
    fuel: str = "diesel"
    engine_cc: int | None = None
    gvw_tonnes: Decimal | None = None
    seats: int | None = None
    mass_in_service_kg: int | None = None
    tpmlm_kg: int | None = None
    co2_g_per_km: Decimal | None = None
    sources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AllInAtHammer:
    hammer_eur: Decimal
    lines: dict[str, Decimal]
    all_in_eur: Decimal
    auction_total_eur: Decimal
    sell_eur: Decimal
    profit_eur: Decimal
    roi: Decimal | None
    postures: dict[str, str]
    notes: tuple[str, ...]


def jurisdiction_from(registration: str | None, provenance: str) -> tuple[str, str]:
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
    fuel_key = (fuel or "diesel").lower()
    if fuel_key == "electric":
        return {
            "candidate_taric_code": "87046090",
            "third_country_duty_rate": "0.10",
            "source": "https://ec.europa.eu/taxation_customs/dds2/taric/measures.jsp?Lang=en&Taric=87046090",
            "effective_date": "1999-01-01",
            "classification_confidence": "LOW",
            "label": "ESTIMATED TARIFF CLASSIFICATION",
            "inputs": {"fuel": fuel_key, "gvw_tonnes": str(gvw_tonnes) if gvw_tonnes else None, "engine_cc": engine_cc},
            "note": "Electric goods vehicle candidate. Confirm the exact TARIC leaf before filing.",
        }
    if gvw_tonnes is None:
        return {
            "candidate_taric_code": "",
            "third_country_duty_rate": "0.22",
            "source": TARIC_SOURCE_87042139,
            "effective_date": "1999-01-01",
            "classification_confidence": "LOW",
            "label": "ESTIMATED TARIFF CLASSIFICATION",
            "inputs": {"fuel": fuel_key, "gvw_tonnes": None, "engine_cc": engine_cc},
            "note": "GVW unknown. Conservative used-diesel leaf uses the higher 22% band until GVW and engine capacity are known.",
        }
    if used and gvw_tonnes <= 5 and engine_cc is not None and engine_cc <= 2500:
        return {
            "candidate_taric_code": "87042199",
            "third_country_duty_rate": "0.10",
            "source": TARIC_SOURCE_87042199,
            "effective_date": "1999-01-01",
            "classification_confidence": "MEDIUM",
            "label": "ESTIMATED TARIFF CLASSIFICATION",
            "inputs": {"fuel": fuel_key, "gvw_tonnes": str(gvw_tonnes), "engine_cc": engine_cc},
            "note": "Used diesel goods vehicle, GVW ≤ 5 t, engine ≤ 2 500 cm³. Official third-country duty 10%.",
        }
    if used and gvw_tonnes <= 5 and (engine_cc is None or engine_cc > 2500):
        return {
            "candidate_taric_code": "87042139",
            "third_country_duty_rate": "0.22",
            "source": TARIC_SOURCE_87042139,
            "effective_date": "1999-01-01",
            "classification_confidence": "MEDIUM" if engine_cc else "LOW",
            "label": "ESTIMATED TARIFF CLASSIFICATION",
            "inputs": {"fuel": fuel_key, "gvw_tonnes": str(gvw_tonnes), "engine_cc": engine_cc},
            "note": "Used diesel goods vehicle, GVW ≤ 5 t, engine > 2 500 cm³ or unknown. Official third-country duty 22%.",
        }
    return {
        "candidate_taric_code": "",
        "third_country_duty_rate": "0.22",
        "source": TARIC_SOURCE_87042139,
        "effective_date": "1999-01-01",
        "classification_confidence": "LOW",
        "label": "ESTIMATED TARIFF CLASSIFICATION",
        "inputs": {"fuel": fuel_key, "gvw_tonnes": str(gvw_tonnes) if gvw_tonnes else None, "engine_cc": engine_cc},
        "note": "Conservative duty band until a tighter leaf is evidenced.",
    }


def spec_from_evaluation(evaluation: dict) -> VehicleSpec:
    """Build screening attributes from catalogue text only. Do not invent GVW/seats/CO2."""

    vehicle = " ".join(
        str(evaluation.get(key) or "")
        for key in ("title", "vehicle", "listing_title", "derivative")
    ).lower()
    fuel = "diesel"
    if "electric" in vehicle or "edeliver" in vehicle or " e-" in vehicle or "ev " in vehicle:
        fuel = "electric"
    elif "petrol" in vehicle or "gasoline" in vehicle:
        fuel = "petrol"
    engine_cc = _engine_cc(vehicle)
    gvw = None
    seats = None
    mass = None
    tpmlm = None
    co2 = None
    sources: list[str] = []
    retrieved = TARIC_CHECKED
    if engine_cc:
        sources.append(f"engine_cc={engine_cc} cm³ from catalogue text; posture=ESTIMATED; retrieved={retrieved}")
    else:
        sources.append(f"engine_cc unresolved from catalogue; posture=UNKNOWN; retrieved={retrieved}")
    sources.append(f"fuel={fuel} from catalogue text; posture=ESTIMATED; retrieved={retrieved}")
    sources.append(f"GVW/TPMLM/seats/CO2 not invented; posture=UNKNOWN until CoC/NSSTA/IVA; retrieved={retrieved}")
    homologation = evaluation.get("homologation") or {}
    if homologation.get("tpmlm_kg"):
        tpmlm = int(homologation["tpmlm_kg"])
        gvw = (Decimal(tpmlm) / Decimal("1000")).quantize(Decimal("0.1"))
        sources.append(f"tpmlm_kg={tpmlm} from homologation evidence; posture=PROVEN; retrieved={retrieved}")
    if homologation.get("mass_in_service_kg"):
        mass = int(homologation["mass_in_service_kg"])
        sources.append(f"mass_in_service_kg={mass} from homologation evidence; posture=PROVEN; retrieved={retrieved}")
    if homologation.get("seats") is not None:
        seats = int(homologation["seats"])
        sources.append(f"seats={seats} from homologation evidence; posture=PROVEN; retrieved={retrieved}")
    if homologation.get("co2_g_per_km") is not None:
        co2 = Decimal(str(homologation["co2_g_per_km"]))
        sources.append(f"co2={co2} from homologation evidence; posture=PROVEN; retrieved={retrieved}")
    return VehicleSpec(
        fuel=fuel,
        engine_cc=engine_cc,
        gvw_tonnes=gvw,
        seats=seats,
        mass_in_service_kg=mass,
        tpmlm_kg=tpmlm,
        co2_g_per_km=co2,
        sources=tuple(sources),
    )


def _engine_cc(text: str) -> int | None:
    import re

    # Prefer explicit litre tokens next to diesel markers, then bare X.Y, then cm³.
    match = re.search(r"\b(\d)\.(\d)\s*(?:tdi|tdci|cdti|hdi|dci|turbo\s*d|ecoblue|multijet|bluehdi|litre|liter)?\b", text)
    if match:
        litres = Decimal(f"{match.group(1)}.{match.group(2)}")
        if Decimal("0.8") <= litres <= Decimal("6.0"):
            return int(litres * 1000)
    match = re.search(r"\b(\d{3,4})\s*(?:cc|cm3|cm³)\b", text)
    if match:
        return int(match.group(1))
    return None


def vrt_scenarios(*, sell_eur: Decimal, spec: VehicleSpec, homologation: dict | None = None) -> dict:
    """Safe VRT is the higher defensible figure until €200 eligibility is supported."""

    euro200_ok = False
    if homologation and homologation.get("seats") is not None and homologation.get("mass_in_service_kg") and homologation.get("tpmlm_kg"):
        seats = int(homologation["seats"])
        mass = int(homologation["mass_in_service_kg"])
        tpmlm = int(homologation["tpmlm_kg"])
        fuel = Fuel.ELECTRIC if spec.fuel == "electric" else Fuel.DIESEL
        euro200_ok = seats < 4 and _flat_200_ratio(fuel, mass, tpmlm)
    # ESTIMATED OMSP = conservative Irish resale. Not Revenue OMSP.
    omsp = sell_eur
    co2 = spec.co2_g_per_km if spec.co2_g_per_km is not None else Decimal("150")
    category_b = category_b_co2_charge(omsp, co2)
    if euro200_ok:
        safe = VRT_200
        safe_label = "€200 VRT — N1 weight test supported"
        posture = "ESTIMATED"
    else:
        safe = category_b
        safe_label = "Category B estimate using estimated OMSP and CO2 > 120 g/km unless a lower figure is evidenced"
        posture = "ESTIMATED"
    return {
        "safe_vrt_eur": safe,
        "vrt_if_200_eur": VRT_200,
        "category_b_eur": category_b,
        "euro200_supported": euro200_ok,
        "safe_label": safe_label,
        "posture": posture,
        "omsp_estimate_eur": str(omsp),
        "co2_assumed": str(co2),
        "source": REVENUE_APPLYING_TAX,
    }


def selling_cost_eur(sell: Decimal) -> Decimal:
    return money(max(sell * SELLING_FRICTION_RATE, SELLING_FRICTION_FLOOR_EUR))


def default_t426_schedule(fx: Decimal) -> AuctionFeeSchedule:
    """Mid Ulster commercial bands from the frozen T426 catalogue, converted at the auction FX."""

    bands_gbp = ((Decimal("1000"), Decimal("150")), (Decimal("3000"), Decimal("250")), (None, Decimal("350")))
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    return AuctionFeeSchedule(
        schedule_id="mid-ulster-T426",
        source_id="mid-ulster",
        version="t426-snapshot-1",
        effective_from=now,
        retrieved_at=now,
        evidence_url="owner-supplied-catalogue",
        applies_to="commercial_vehicles",
        bands=tuple(
            PremiumBand(None if up is None else money(up * fx), Decimal("0"), money(fixed * fx)) for up, fixed in bands_gbp
        ),
        minimum_premium_eur=Decimal("0"),
        premium_vat_rate=Decimal("0.20"),
        documentation_fee_eur=Decimal("0"),
        online_bidding_fee_eur=Decimal("0"),
        collection_fee_eur=Decimal("0"),
    )


def all_in_at_hammer(
    *,
    hammer_eur: Decimal,
    sell_eur: Decimal,
    schedule: AuctionFeeSchedule | None,
    vat_treatment: AuctionVatTreatment,
    hammer_includes_vat: bool | None,
    lot_vat_rate: Decimal | None,
    duty_rate: Decimal,
    vrt_eur: Decimal,
    transport_eur: Decimal = TRANSPORT_ESTIMATE_EUR,
    insurance_eur: Decimal = INSURANCE_ESTIMATE_EUR,
    registration_eur: Decimal = REGISTRATION_ESTIMATE_EUR,
    repairs_eur: Decimal = UNKNOWN_MECHANICAL_EXPECTED_EUR,
    ni_clear: bool = False,
) -> AllInAtHammer:
    percent = Decimal(str(settings.payment_fee_percent))
    fixed = Decimal(str(settings.payment_fee_fixed_eur))
    payment = money(hammer_eur * percent + fixed)
    auction = auction_costs(
        hammer_eur=hammer_eur,
        schedule=schedule,
        vat_treatment=vat_treatment,
        hammer_is_vat_inclusive=hammer_includes_vat,
        owner_vat_registered=False,
        commercial_vat_invoice_expected=False,
        payment_fee_eur=payment,
        payment_fee_posture=EvidencePosture.ESTIMATED,
        lot_vat_rate=lot_vat_rate,
    )
    lines: dict[str, Decimal] = {}
    postures: dict[str, str] = {}
    for line in auction.lines:
        if line.name == "auction_lot_vat_cash" or line.amount_eur is None:
            continue
        lines[line.name] = line.amount_eur
        postures[line.name] = line.posture.value
    auction_total = auction.economic_total_eur or ZERO
    if ni_clear:
        duty = ZERO
        import_vat = ZERO
        postures["customs_duty"] = "CALCULATED"
        postures["import_vat"] = "CALCULATED"
    else:
        customs_value = money(hammer_eur + transport_eur + insurance_eur)
        duty = money(customs_value * duty_rate)
        import_vat = money((customs_value + duty) * VAT_RATE)
        postures["customs_duty"] = "ESTIMATED"
        postures["import_vat"] = "CALCULATED"
    sell_cost = selling_cost_eur(sell_eur)
    lines.update(
        {
            "customs_duty": duty,
            "import_vat": import_vat,
            "vrt": vrt_eur,
            "registration": registration_eur,
            "transport": transport_eur,
            "insurance": insurance_eur,
            "reconditioning": repairs_eur,
            "selling_cost": sell_cost,
        }
    )
    postures.update(
        {
            "vrt": "ESTIMATED",
            "registration": "ESTIMATED",
            "transport": "ESTIMATED",
            "insurance": "ESTIMATED",
            "reconditioning": "ESTIMATED",
            "selling_cost": "ESTIMATED",
        }
    )
    all_in = money(sum(lines.values(), ZERO))
    profit = money(sell_eur - all_in)
    return AllInAtHammer(
        hammer_eur=money(hammer_eur),
        lines=lines,
        all_in_eur=all_in,
        auction_total_eur=money(auction_total),
        sell_eur=money(sell_eur),
        profit_eur=profit,
        roi=roi_at(profit_eur=profit, all_in_eur=all_in),
        postures=postures,
        notes=("Auction fees from AuctionFeeSchedule / auction_costs().", "Import VAT uses Revenue 23%.", "Selling friction is included once in all-in."),
    )


def _feasible(result: AllInAtHammer, *, quick_sale_eur: Decimal, required_profit: Decimal, required_roi: Decimal) -> bool:
    if result.profit_eur < required_profit:
        return False
    if result.roi is None or result.roi < required_roi:
        return False
    purchase = money(result.all_in_eur - result.lines["selling_cost"])
    downside_profit = money(quick_sale_eur - purchase - selling_cost_eur(quick_sale_eur))
    return downside_profit >= ZERO


def solve_owner_max_hammer(
    *,
    sell_eur: Decimal,
    quick_sale_eur: Decimal,
    schedule: AuctionFeeSchedule | None,
    vat_treatment: AuctionVatTreatment,
    hammer_includes_vat: bool | None,
    lot_vat_rate: Decimal | None,
    duty_rate: Decimal,
    vrt_eur: Decimal,
    ni_clear: bool = False,
    required_profit: Decimal = REQUIRED_ABSOLUTE_PROFIT_EUR,
    required_roi: Decimal = REQUIRED_ROI,
) -> AllInAtHammer | None:
    def landed(hammer: Decimal) -> AllInAtHammer:
        return all_in_at_hammer(
            hammer_eur=hammer,
            sell_eur=sell_eur,
            schedule=schedule,
            vat_treatment=vat_treatment,
            hammer_includes_vat=hammer_includes_vat,
            lot_vat_rate=lot_vat_rate,
            duty_rate=duty_rate,
            vrt_eur=vrt_eur,
            ni_clear=ni_clear,
        )

    probe = landed(ZERO)
    if not _feasible(probe, quick_sale_eur=quick_sale_eur, required_profit=required_profit, required_roi=required_roi):
        return None
    high = int((sell_eur * 100).to_integral_value())
    low = 0
    best = 0
    while low <= high:
        mid = (low + high) // 2
        result = landed(Decimal(mid) / Decimal("100"))
        if _feasible(result, quick_sale_eur=quick_sale_eur, required_profit=required_profit, required_roi=required_roi):
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    hammer = money_down(Decimal(best) / Decimal("100"))
    result = landed(hammer)
    while hammer > ZERO and not _feasible(result, quick_sale_eur=quick_sale_eur, required_profit=required_profit, required_roi=required_roi):
        hammer = money_down(hammer - Decimal("0.01"))
        result = landed(hammer)
    if not _feasible(result, quick_sale_eur=quick_sale_eur, required_profit=required_profit, required_roi=required_roi):
        return None
    return result


def build_scenarios(
    evaluation: dict,
    *,
    registration: str = "",
    fx: str = "",
    schedule: AuctionFeeSchedule | None = None,
    vat_treatment: AuctionVatTreatment = AuctionVatTreatment.STANDARD_ON_HAMMER,
    hammer_includes_vat: bool | None = False,
    lot_vat_rate: Decimal | None = Decimal("0.20"),
) -> dict:
    valuation = evaluation.get("valuation") or {}
    provenance = str(evaluation.get("provenance_status") or "")
    sell = valuation.get("conservative_eur") or valuation.get("expected_achievable_eur")
    quick = valuation.get("quick_sale_eur") or sell
    if not sell or not quick:
        return _empty(registration, provenance)
    sell_d = Decimal(str(sell))
    quick_d = Decimal(str(quick))
    fx_d = Decimal(fx) if fx else Decimal("0")
    if schedule is None and fx_d > 0:
        schedule = default_t426_schedule(fx_d)
    jurisdiction, tax_status = jurisdiction_from(registration, provenance)
    spec = spec_from_evaluation(evaluation)
    taric = candidate_taric(fuel=spec.fuel, gvw_tonnes=spec.gvw_tonnes, engine_cc=spec.engine_cc)
    duty_rate = Decimal(str(taric["third_country_duty_rate"] or "0.22"))
    vrt = vrt_scenarios(sell_eur=sell_d, spec=spec)
    safe_vrt = Decimal(str(vrt["safe_vrt_eur"]))
    vrt_200 = Decimal(str(vrt["vrt_if_200_eur"]))
    ni_proven = tax_status == "PROVEN" and jurisdiction == "LIKELY_NI"

    safe = solve_owner_max_hammer(
        sell_eur=sell_d,
        quick_sale_eur=quick_d,
        schedule=schedule,
        vat_treatment=vat_treatment,
        hammer_includes_vat=hammer_includes_vat,
        lot_vat_rate=lot_vat_rate,
        duty_rate=Decimal("0") if ni_proven else duty_rate,
        vrt_eur=safe_vrt,
        ni_clear=ni_proven,
    )
    alt_ni = None
    alt_uk = None
    alt_vrt = None
    if jurisdiction == "LIKELY_NI" and not ni_proven:
        alt_ni = solve_owner_max_hammer(
            sell_eur=sell_d,
            quick_sale_eur=quick_d,
            schedule=schedule,
            vat_treatment=vat_treatment,
            hammer_includes_vat=hammer_includes_vat,
            lot_vat_rate=lot_vat_rate,
            duty_rate=Decimal("0"),
            vrt_eur=safe_vrt,
            ni_clear=True,
        )
        alt_vrt = solve_owner_max_hammer(
            sell_eur=sell_d,
            quick_sale_eur=quick_d,
            schedule=schedule,
            vat_treatment=vat_treatment,
            hammer_includes_vat=hammer_includes_vat,
            lot_vat_rate=lot_vat_rate,
            duty_rate=Decimal("0"),
            vrt_eur=vrt_200,
            ni_clear=True,
        )
    if jurisdiction == "LIKELY_GB":
        alt_uk = solve_owner_max_hammer(
            sell_eur=sell_d,
            quick_sale_eur=quick_d,
            schedule=schedule,
            vat_treatment=vat_treatment,
            hammer_includes_vat=hammer_includes_vat,
            lot_vat_rate=lot_vat_rate,
            duty_rate=Decimal("0"),
            vrt_eur=safe_vrt,
            ni_clear=False,
        )
        alt_vrt = solve_owner_max_hammer(
            sell_eur=sell_d,
            quick_sale_eur=quick_d,
            schedule=schedule,
            vat_treatment=vat_treatment,
            hammer_includes_vat=hammer_includes_vat,
            lot_vat_rate=lot_vat_rate,
            duty_rate=duty_rate,
            vrt_eur=vrt_200,
            ni_clear=False,
        )

    confidence = "ESTIMATED"
    if safe and not vrt["euro200_supported"] and Decimal(str(vrt["safe_vrt_eur"])) >= Decimal(str(vrt["category_b_eur"])):
        # Conservative Category B VRT is in force for the primary bid.
        confidence = "SAFE" if taric["classification_confidence"] in {"MEDIUM", "HIGH"} else "ESTIMATED"
    if safe and vrt["euro200_supported"]:
        confidence = "SAFE" if taric["classification_confidence"] in {"MEDIUM", "HIGH"} else "ESTIMATED"
    if not safe:
        label = "ESTIMATED MAX BID — VRT RANGE UNRESOLVED" if not sell else "ESTIMATED MAX BID — HURDLES NOT MET"
    elif jurisdiction == "LIKELY_NI" and not ni_proven:
        label = "SAFE WITHOUT NI PROOF"
    elif jurisdiction == "LIKELY_GB":
        label = "SAFE GB IMPORT"
    elif confidence == "SAFE":
        label = "SAFE MAX BID"
    else:
        label = "ESTIMATED MAX BID"

    return {
        "jurisdiction": jurisdiction,
        "tax_status": tax_status,
        "bid_label": label,
        "tax_confidence": confidence,
        "safe_max_bid_gbp": _gbp(safe.hammer_eur if safe else None, fx),
        "safe_max_bid_eur": str(safe.hammer_eur) if safe else None,
        "alt_max_bid_gbp": _gbp((alt_ni or alt_uk).hammer_eur if (alt_ni or alt_uk) else None, fx),
        "alt_label": "IF NI STATUS PROVEN" if alt_ni else ("IF UK ORIGIN PROVEN" if alt_uk else ""),
        "alt_vrt_max_bid_gbp": _gbp(alt_vrt.hammer_eur if alt_vrt else None, fx),
        "alt_vrt_label": "IF NI + €200 VRT PROVEN" if alt_ni else ("IF €200 VRT PROVEN" if alt_vrt else ""),
        "potential_saving_eur": str(money((alt_ni or alt_uk).hammer_eur - safe.hammer_eur)) if safe and (alt_ni or alt_uk) else None,
        "sell_eur": str(sell_d),
        "fees_and_tax_eur": str(_fees_taxes(safe)) if safe else None,
        "profit_eur": str(safe.profit_eur) if safe else None,
        "roi": str(safe.roi) if safe and safe.roi is not None else None,
        "all_in_eur": str(safe.all_in_eur) if safe else None,
        "auction_charges_eur": str(safe.auction_total_eur - safe.hammer_eur) if safe else None,
        "hammer_eur": str(safe.hammer_eur) if safe else None,
        "customs_eur": str(safe.lines.get("customs_duty")) if safe else None,
        "import_vat_eur": str(safe.lines.get("import_vat")) if safe else None,
        "vrt_eur": str(safe.lines.get("vrt")) if safe else None,
        "registration_eur": str(safe.lines.get("registration")) if safe else None,
        "transport_eur": str(safe.lines.get("transport")) if safe else None,
        "insurance_eur": str(safe.lines.get("insurance")) if safe else None,
        "repairs_eur": str(safe.lines.get("reconditioning")) if safe else None,
        "selling_cost_eur": str(safe.lines.get("selling_cost")) if safe else None,
        "buyer_premium_eur": str(safe.lines.get("buyer_premium")) if safe else None,
        "premium_vat_eur": str(safe.lines.get("premium_vat")) if safe else None,
        "lot_vat_eur": str(safe.lines.get("auction_lot_vat")) if safe else None,
        "payment_fee_eur": str(safe.lines.get("payment_fee")) if safe else None,
        "lines": {key: str(value) for key, value in safe.lines.items()} if safe else {},
        "postures": safe.postures if safe else {},
        "taric": taric,
        "vrt": vrt,
        "spec": {"fuel": spec.fuel, "engine_cc": spec.engine_cc, "gvw_tonnes": str(spec.gvw_tonnes) if spec.gvw_tonnes else None, "sources": list(spec.sources)},
        "documents": _documents(jurisdiction, tax_status, vrt["euro200_supported"]),
        "sources": _sources(),
        "scenario_name": "NI_PROVEN" if ni_proven else ("GB_STANDARD" if jurisdiction != "LIKELY_NI" else "GB_FALLBACK_FOR_UNPROVEN_NI"),
        "required_profit_eur": str(REQUIRED_ABSOLUTE_PROFIT_EUR),
        "required_roi": str(REQUIRED_ROI),
    }


def _fees_taxes(result: AllInAtHammer) -> Decimal:
    keys = ("customs_duty", "import_vat", "vrt", "registration", "transport", "insurance", "reconditioning", "buyer_premium", "premium_vat", "auction_lot_vat", "payment_fee", "documentation_fee", "online_bidding_fee", "collection_fee")
    return money(sum((result.lines.get(key, ZERO) for key in keys), ZERO))


def _empty(registration: str, provenance: str) -> dict:
    jurisdiction, tax_status = jurisdiction_from(registration, provenance)
    return {
        "jurisdiction": jurisdiction,
        "tax_status": tax_status,
        "bid_label": "ESTIMATED MAX BID — VRT RANGE UNRESOLVED",
        "tax_confidence": "UNKNOWN",
        "safe_max_bid_gbp": None,
        "alt_max_bid_gbp": None,
        "alt_label": "",
        "sell_eur": None,
        "fees_and_tax_eur": None,
        "profit_eur": None,
        "documents": _documents(jurisdiction, tax_status, False),
        "sources": _sources(),
        "taric": {},
        "lines": {},
        "postures": {},
    }


def _gbp(eur: Decimal | None, fx: str) -> str | None:
    if eur is None or not fx:
        return None
    rate = Decimal(fx)
    if rate <= 0:
        return None
    return str((eur / rate).quantize(Decimal("0.01")))


def _documents(jurisdiction: str, tax_status: str, euro200: bool) -> list[str]:
    docs: list[str] = []
    if jurisdiction == "LIKELY_NI" and tax_status != "PROVEN":
        docs.extend(["NI import declaration tied to the VIN", "or original V5C (NI keeper) + NI service history + NI MOT history"])
    if jurisdiction == "LIKELY_GB":
        docs.append("UK preferential origin statement if claiming 0% duty")
    if not euro200:
        docs.append("CoC / NSSTA / IVA with seats, mass in service, and TPMLM for €200 VRT")
    return docs


def _sources() -> list[dict[str, str]]:
    return [
        {"id": "taric", "url": TARIC_SOURCE_87042199, "checked": TARIC_CHECKED, "note": "EU TARIC third-country duty"},
        {"id": "ni", "url": REVENUE_NI, "checked": TARIC_CHECKED, "note": "NI customs duty and import VAT relief"},
        {"id": "vat", "url": REVENUE_VAT_RATES, "checked": TARIC_CHECKED, "note": "Standard VAT 23%"},
        {"id": "vrt", "url": REVENUE_APPLYING_TAX, "checked": TARIC_CHECKED, "note": "Category B and €200 N1 VRT"},
    ]
