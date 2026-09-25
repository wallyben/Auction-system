"""Irish VRT, NOx, customs duty, and import VAT for commercial vans.

Rules are transcribed from Revenue pages retrieved 2026-09-22 and rechecked 2026-09-25.
They are operational calculations, not tax advice. A missing input stays unknown.
The 2026-09-25 recheck confirmed the standard rate remains 23% from 1 January 2026.
The margin scheme is optional and is not assumed. GB-origin vehicles imported via NI
are outside the margin scheme. Vehicle-specific evidence still decides treatment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from app.core.money import ZERO, money
from app.domains.vehicles.enums import Co2Basis, EvidencePosture, Fuel, ProvenanceState, VrtState
from app.domains.vehicles.evidence import EvidenceLedger, EvidenceRecord, MoneyLine
from app.domains.vehicles.policy import TAX_RULE_VERSION, TAX_RULES_RETRIEVED_AT

REVENUE_APPLYING_TAX = "https://www.revenue.ie/en/vrt/calculating-vrt/applying-tax.aspx"
REVENUE_VAT_RATES = "https://www.revenue.ie/en/vat/vat-rates/search-vat-rates/current-VAT-rates.aspx"
REVENUE_VAT_CUSTOMS = "https://www.revenue.ie/en/vrt/calculating-vrt/vat-customs-duty.aspx"
REVENUE_GB_NI = "https://www.revenue.ie/en/vrt/registration-of-imported-used-vehicles/index.aspx"
REVENUE_ORIGIN = "https://www.revenue.ie/en/customs/documents/ccc/ccc79-preferential-origin-and-returned-goods-relief.pdf"
REVENUE_MARGIN = "https://www.revenue.ie/en/vat/vat-on-goods/schemes/margin-scheme/index.aspx"
REVENUE_GB_NI_VAT = "https://www.revenue.ie/en/tax-professionals/tdm/value-added-tax/movement-of-second-motor-vehicles-from-gb-and-ni/movement-of-second-hand-motor-vehicles-from-gb-ni.pdf"
TAX_RULES_RECHECKED_AT = "2026-09-25"
REVENUE_NI = "https://www.revenue.ie/en/vrt/registration-of-imported-used-vehicles/registering-vehicles-from-ni.aspx"
REVENUE_EV = "https://www.revenue.ie/en/vrt/reliefs-and-exemptions/electric-vehicles/index.aspx"

TAX_RULES = (
    {"id": "ni-import", "description": "NI customs duty and import VAT relief", "effective": "2021-01-01", "url": REVENUE_NI, "checked": TAX_RULES_RECHECKED_AT},
    {"id": "gb-import", "description": "GB import duty and import VAT", "effective": "2021-01-01", "url": REVENUE_GB_NI_VAT, "checked": TAX_RULES_RECHECKED_AT},
    {"id": "vat-standard", "description": "Standard VAT 23%", "effective": "2026-01-01", "url": REVENUE_VAT_RATES, "checked": TAX_RULES_RECHECKED_AT},
    {"id": "uk-origin", "description": "Preferential UK origin is not implied by a GB plate", "effective": "2021-01-01", "url": REVENUE_ORIGIN, "checked": TAX_RULES_RECHECKED_AT},
    {"id": "category-b", "description": "Category B VRT 8% or 13.3%", "effective": "2025-07-01", "url": REVENUE_APPLYING_TAX, "checked": TAX_RULES_RECHECKED_AT},
    {"id": "n1-200", "description": "€200 N1 VRT where seats and mass tests pass", "effective": "2025-07-01", "url": REVENUE_APPLYING_TAX, "checked": TAX_RULES_RECHECKED_AT},
    {"id": "ev-relief", "description": "Electric Category A/B relief up to €5,000 through 31 Dec 2026", "effective": "2026-01-01", "url": REVENUE_EV, "checked": TAX_RULES_RECHECKED_AT},
    {"id": "vrt-calculator", "description": "Revenue calculator is an estimate; registration decides the exact VRT", "effective": "2026-01-01", "url": "https://www.ros.ie/evrt-enquiry/vrtenquiry.html", "checked": TAX_RULES_RECHECKED_AT},
)


def ev_vrt_relief_cap_eur(*, electric: bool, before_deadline: bool = True) -> Decimal | None:
    """Official cap. The exact OMSP taper is Revenue's calculator, not a guessed slope."""

    if not electric or not before_deadline:
        return None
    return Decimal("5000")

VAT_RATE = Decimal("0.23")
VAT_EFFECTIVE = datetime(2026, 1, 1, tzinfo=timezone.utc)

# Category A CO2 bands, "up to and including" the upper bound. Retrieved 2026-09-22.
_CATEGORY_A_BANDS: tuple[tuple[Decimal, Decimal, Decimal], ...] = (
    (Decimal("50"), Decimal("0.07"), Decimal("140")),
    (Decimal("80"), Decimal("0.09"), Decimal("180")),
    (Decimal("85"), Decimal("0.0975"), Decimal("195")),
    (Decimal("90"), Decimal("0.105"), Decimal("210")),
    (Decimal("95"), Decimal("0.1125"), Decimal("225")),
    (Decimal("100"), Decimal("0.12"), Decimal("240")),
    (Decimal("105"), Decimal("0.1275"), Decimal("255")),
    (Decimal("110"), Decimal("0.135"), Decimal("270")),
    (Decimal("115"), Decimal("0.1525"), Decimal("305")),
    (Decimal("120"), Decimal("0.16"), Decimal("320")),
    (Decimal("125"), Decimal("0.1675"), Decimal("335")),
    (Decimal("130"), Decimal("0.175"), Decimal("350")),
    (Decimal("135"), Decimal("0.1925"), Decimal("385")),
    (Decimal("140"), Decimal("0.20"), Decimal("400")),
    (Decimal("145"), Decimal("0.215"), Decimal("430")),
    (Decimal("150"), Decimal("0.25"), Decimal("500")),
    (Decimal("155"), Decimal("0.275"), Decimal("550")),
    (Decimal("170"), Decimal("0.30"), Decimal("600")),
    (Decimal("190"), Decimal("0.35"), Decimal("700")),
)
_CATEGORY_A_TOP = (Decimal("0.41"), Decimal("820"))


@dataclass(frozen=True, slots=True)
class Homologation:
    """CoC / NSSTA / IVA. Listing text is not homologation."""

    eu_category: str
    seats: int
    mass_in_service_kg: int
    tpmlm_kg: int
    document: str
    reference: str
    separate_passenger_and_cargo_units: bool = False


@dataclass(frozen=True, slots=True)
class TaxInput:
    provenance: ProvenanceState
    fuel: Fuel
    seats: int | None = None
    homologation: Homologation | None = None
    co2_g_per_km: Decimal | None = None
    co2_basis: Co2Basis = Co2Basis.UNKNOWN
    nox_mg_per_km: Decimal | None = None
    omsp_eur: Decimal | None = None
    omsp_source: str | None = None
    customs_value_eur: Decimal | None = None
    duty_rate: Decimal | None = None
    preferential_origin_proven: bool = False
    registration_fee_eur: Decimal | None = None
    registration_fee_posture: EvidencePosture = EvidencePosture.UNKNOWN


@dataclass(frozen=True, slots=True)
class TaxPosition:
    vrt_state: VrtState
    vrt_eur: Decimal | None
    vrt_posture: EvidencePosture
    nox_eur: Decimal | None
    nox_posture: EvidencePosture
    customs_duty_eur: Decimal | None
    customs_posture: EvidencePosture
    import_vat_eur: Decimal | None
    import_vat_posture: EvidencePosture
    registration_eur: Decimal | None
    registration_posture: EvidencePosture
    rule_version: str
    blocked: bool
    notes: tuple[str, ...]
    lines: tuple[MoneyLine, ...]


def nox_charge_eur(mg_per_km: Decimal, fuel: Fuel) -> Decimal:
    """Category A NOx levy. Electrics are excluded by the caller."""

    remaining = mg_per_km
    first = min(remaining, Decimal("40"))
    remaining -= first
    second = min(remaining, Decimal("40"))
    remaining -= second
    charge = first * Decimal("5") + second * Decimal("15") + remaining * Decimal("25")
    cap = Decimal("4850") if fuel is Fuel.DIESEL else Decimal("600")
    return money(min(charge, cap))


def wltp_co2(co2: Decimal, basis: Co2Basis, fuel: Fuel) -> Decimal | None:
    if basis is Co2Basis.WLTP:
        return co2
    if basis is not Co2Basis.NEDC:
        return None
    if fuel is Fuel.DIESEL:
        return (co2 * Decimal("0.9498")) + Decimal("41.539")
    return (co2 * Decimal("1.0105")) + Decimal("18.335")


def category_a_co2_charge(omsp: Decimal, co2: Decimal) -> Decimal:
    for upper, rate, floor in _CATEGORY_A_BANDS:
        if co2 <= upper:
            return money(max(omsp * rate, floor))
    rate, floor = _CATEGORY_A_TOP
    return money(max(omsp * rate, floor))


def category_b_co2_charge(omsp: Decimal, co2: Decimal) -> Decimal:
    if co2 <= Decimal("120"):
        return money(max(omsp * Decimal("0.08"), Decimal("160")))
    return money(max(omsp * Decimal("0.133"), Decimal("266")))


def _flat_200_ratio(fuel: Fuel, mass: int, tpmlm: int) -> bool:
    if mass <= 0:
        return False
    ratio = Decimal(tpmlm) / Decimal(mass)
    threshold = Decimal("1.25") if fuel is Fuel.ELECTRIC else Decimal("1.30")
    return ratio > threshold


def _customs(data: TaxInput, ledger: EvidenceLedger) -> tuple[Decimal | None, EvidencePosture, Decimal | None, EvidencePosture, list[str]]:
    notes: list[str] = []
    clear_states = {
        ProvenanceState.ROI_NATIVE,
        ProvenanceState.NI_PRE_2021_PROVEN,
        ProvenanceState.NI_POST_2020_IMPORT_PROVEN,
    }
    if data.provenance in clear_states:
        note = "Provenance state does not attract Irish customs duty or import VAT."
        notes.append(note)
        ledger.add(
            EvidenceRecord(
                field="import_vat",
                posture=EvidencePosture.PROVEN,
                status="NOT_DUE",
                confidence=Decimal("0.9"),
                source=TAX_RULE_VERSION,
                interpretation=note,
                blocking=False,
                source_url=REVENUE_GB_NI,
                retrieved_at=TAX_RULES_RETRIEVED_AT,
            )
        )
        return ZERO, EvidencePosture.PROVEN, ZERO, EvidencePosture.PROVEN, notes

    if data.provenance not in {ProvenanceState.GB_ORIGIN, ProvenanceState.GB_TO_NI_UNPROVEN}:
        notes.append("Customs status is not established. Duty and import VAT are unknown, not zero.")
        return None, EvidencePosture.UNKNOWN, None, EvidencePosture.UNKNOWN, notes

    if data.customs_value_eur is None:
        notes.append("Customs value needs the price plus transport and insurance to the border. It was not supplied.")
        return None, EvidencePosture.UNKNOWN, None, EvidencePosture.UNKNOWN, notes

    if data.preferential_origin_proven:
        duty_rate = ZERO
        duty_posture = EvidencePosture.PROVEN
        notes.append("Preferential origin was marked proven. Duty rate used is 0. A statement of origin must actually exist.")
    elif data.duty_rate is not None:
        duty_rate = data.duty_rate
        duty_posture = EvidencePosture.ESTIMATED
        notes.append(
            "Duty rate was supplied as an estimate. ARIE does not assume 10% for vans. "
            "TARIC depends on the exact CN code, and UK origin is not implied by a GB registration."
        )
    else:
        notes.append("No TARIC duty rate and no proven preferential origin. Duty is unknown, not 10%.")
        return None, EvidencePosture.UNKNOWN, None, EvidencePosture.UNKNOWN, notes

    duty = money(data.customs_value_eur * duty_rate)
    import_vat = money((data.customs_value_eur + duty) * VAT_RATE)
    notes.append("Import VAT is 23% of customs value plus duty. It is not treated as recoverable.")
    return duty, duty_posture, import_vat, EvidencePosture.PROVEN if data.preferential_origin_proven else EvidencePosture.ESTIMATED, notes


def assess_tax(data: TaxInput, ledger: EvidenceLedger) -> TaxPosition:
    notes: list[str] = [
        f"Tax rule version {TAX_RULE_VERSION}, retrieved {TAX_RULES_RETRIEVED_AT.date().isoformat()}.",
        "Standard VAT 23% from 1 January 2026.",
        f"Rechecked {TAX_RULES_RECHECKED_AT} against {REVENUE_VAT_RATES}, {REVENUE_MARGIN}, and {REVENUE_GB_NI_VAT}.",
        "Margin scheme is optional. It is not applied unless the vehicle's acquisition evidence selects it.",
        "A GB-origin vehicle imported through NI is outside the margin scheme. Resale VAT then follows normal rules.",
        "FULL_OUTPUT_VAT_STRESS divides a cash floor by 1.23. That is a downside screen, not a ruling.",
    ]
    duty, duty_posture, import_vat, import_posture, customs_notes = _customs(data, ledger)
    notes.extend(customs_notes)

    if data.provenance is ProvenanceState.ROI_NATIVE:
        vrt_state = VrtState.VRT_CONFIRMED
        vrt_amount: Decimal | None = ZERO
        vrt_posture = EvidencePosture.PROVEN
        nox_amount: Decimal | None = ZERO
        nox_posture = EvidencePosture.PROVEN
        notes.append("Already on the Irish register. No additional VRT or NOx is modelled.")
    else:
        vrt_state, vrt_amount, vrt_posture, nox_amount, nox_posture, vrt_notes = _vrt(data, ledger)
        notes.extend(vrt_notes)

    if data.provenance is ProvenanceState.ROI_NATIVE:
        registration = ZERO
        registration_posture = EvidencePosture.PROVEN
    else:
        registration = data.registration_fee_eur
        registration_posture = data.registration_fee_posture
        if registration is None or registration_posture is EvidencePosture.UNKNOWN:
            notes.append("Registration or plate fee was not evidenced. It is not assumed to be zero.")

    blocked = any(
        posture is EvidencePosture.UNKNOWN
        for posture in (vrt_posture, nox_posture, duty_posture, import_posture, registration_posture)
    ) or vrt_state is not VrtState.VRT_CONFIRMED

    lines = (
        MoneyLine("vrt", vrt_amount, vrt_posture, TAX_RULE_VERSION, vrt_state.value),
        MoneyLine("nox", nox_amount, nox_posture, TAX_RULE_VERSION, "Category A only"),
        MoneyLine("customs_duty", duty, duty_posture, TAX_RULE_VERSION, "Not assumed at 10%"),
        MoneyLine("import_vat", import_vat, import_posture, REVENUE_VAT_RATES, "Separate from auction VAT"),
        MoneyLine("registration", registration, registration_posture, "owner_or_ncts", "Not collapsed into VRT"),
    )
    return TaxPosition(
        vrt_state=vrt_state,
        vrt_eur=vrt_amount,
        vrt_posture=vrt_posture,
        nox_eur=nox_amount,
        nox_posture=nox_posture,
        customs_duty_eur=duty,
        customs_posture=duty_posture,
        import_vat_eur=import_vat,
        import_vat_posture=import_posture,
        registration_eur=registration,
        registration_posture=registration_posture,
        rule_version=TAX_RULE_VERSION,
        blocked=blocked,
        notes=tuple(notes),
        lines=lines,
    )


def _vrt(
    data: TaxInput,
    ledger: EvidenceLedger,
) -> tuple[VrtState, Decimal | None, EvidencePosture, Decimal | None, EvidencePosture, list[str]]:
    notes: list[str] = []
    homologation = data.homologation
    if homologation is None:
        notes.append("No Certificate of Conformity, NSSTA, or IVA. Model name does not prove €200 VRT.")
        ledger.add(
            EvidenceRecord(
                field="vrt",
                posture=EvidencePosture.UNKNOWN,
                status=VrtState.VRT_REQUIRES_DATA.value,
                confidence=Decimal("0"),
                source=TAX_RULE_VERSION,
                interpretation="Weight, seat count, and EU category were not homologated.",
                blocking=True,
                source_url=REVENUE_APPLYING_TAX,
                retrieved_at=TAX_RULES_RETRIEVED_AT,
            )
        )
        return VrtState.VRT_REQUIRES_DATA, None, EvidencePosture.UNKNOWN, None, EvidencePosture.UNKNOWN, notes

    category = homologation.eu_category.upper()
    seats = homologation.seats
    if category != "N1":
        notes.append(f"Homologation category is {category}, not N1.")
        return VrtState.VRT_NOT_ELIGIBLE, None, EvidencePosture.PROVEN, None, EvidencePosture.UNKNOWN, notes

    category_a = seats >= 4 and not homologation.separate_passenger_and_cargo_units
    flat = (not category_a) and seats < 4 and _flat_200_ratio(data.fuel, homologation.mass_in_service_kg, homologation.tpmlm_kg)
    if flat:
        ledger.add(
            EvidenceRecord(
                field="vrt",
                posture=EvidencePosture.PROVEN,
                status=VrtState.VRT_CONFIRMED.value,
                confidence=Decimal("0.9"),
                source=homologation.document,
                interpretation=(
                    f"{homologation.reference}: N1, {seats} seats, "
                    f"TPMLM {homologation.tpmlm_kg} kg over mass in service {homologation.mass_in_service_kg} kg."
                ),
                blocking=False,
                raw_reference=homologation.reference,
                source_url=REVENUE_APPLYING_TAX,
                retrieved_at=TAX_RULES_RETRIEVED_AT,
            )
        )
        notes.append("€200 VRT is supported by homologation, not by the marketing name.")
        return VrtState.VRT_CONFIRMED, Decimal("200.00"), EvidencePosture.PROVEN, ZERO, EvidencePosture.PROVEN, notes

    if not category_a and seats < 4:
        notes.append("N1 with fewer than four seats does not meet the laden-mass test for €200.")

    co2 = None if data.co2_g_per_km is None else wltp_co2(data.co2_g_per_km, data.co2_basis, data.fuel)
    omsp_ok = data.omsp_eur is not None and data.omsp_source == "revenue_omsp"
    if co2 is None or not omsp_ok:
        state = VrtState.VRT_LIKELY if (not category_a and seats < 4) else VrtState.VRT_REQUIRES_DATA
        notes.append("Percentage VRT needs a CO2 basis and a Revenue OMSP. An Irish asking price is not an OMSP.")
        posture = EvidencePosture.ESTIMATED if state is VrtState.VRT_LIKELY else EvidencePosture.UNKNOWN
        return state, None, posture, None, EvidencePosture.UNKNOWN, notes

    assert data.omsp_eur is not None
    if category_a:
        charge = category_a_co2_charge(data.omsp_eur, co2)
        if data.fuel is Fuel.ELECTRIC:
            nox = ZERO
            nox_posture = EvidencePosture.PROVEN
        elif data.nox_mg_per_km is None:
            notes.append("Category A NOx levy needs a NOx figure. It is not zero.")
            return VrtState.VRT_REQUIRES_DATA, charge, EvidencePosture.ESTIMATED, None, EvidencePosture.UNKNOWN, notes
        else:
            nox = nox_charge_eur(data.nox_mg_per_km, data.fuel)
            nox_posture = EvidencePosture.PROVEN
        notes.append("Four or more seats without separate cargo units are calculated on the Category A table plus NOx.")
        return VrtState.VRT_CONFIRMED, charge, EvidencePosture.PROVEN, nox, nox_posture, notes

    charge = category_b_co2_charge(data.omsp_eur, co2)
    notes.append("Category B CO2 charge since 1 July 2025. NOx is not added to Category B.")
    return VrtState.VRT_CONFIRMED, charge, EvidencePosture.PROVEN, ZERO, EvidencePosture.PROVEN, notes
