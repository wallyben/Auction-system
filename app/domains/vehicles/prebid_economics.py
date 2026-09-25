"""Pre-bid landed cost. A pre-tax ceiling is not a final safe hammer."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.money import money
from app.domains.vehicles.tax import VAT_RATE

_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class LandedView:
    provenance: str
    pre_tax_hammer_ceiling_eur: Decimal | None
    ni_clear_max_hammer_eur: Decimal | None
    gb_preferential_max_hammer_eur: Decimal | None
    gb_confirmed_duty_max_hammer_eur: Decimal | None
    final_max_safe_hammer_eur: Decimal | None
    headroom_eur: Decimal | None
    headroom_status: str
    vrt_200_eligibility: str
    vrt_status: str
    customs_status: str
    import_vat_status: str
    import_vat_cashflow_eur: Decimal | None
    import_vat_economic_eur: Decimal | None
    vat_recovery_posture: str
    tariff_status: str
    candidate_cn_code: str
    blockers: tuple[str, ...]
    diligence: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "provenance": self.provenance,
            "pre_tax_hammer_ceiling_eur": _s(self.pre_tax_hammer_ceiling_eur),
            "ni_clear_max_hammer_eur": _s(self.ni_clear_max_hammer_eur),
            "gb_preferential_max_hammer_eur": _s(self.gb_preferential_max_hammer_eur),
            "gb_confirmed_duty_max_hammer_eur": _s(self.gb_confirmed_duty_max_hammer_eur),
            "final_max_safe_hammer_eur": _s(self.final_max_safe_hammer_eur),
            "headroom_eur": _s(self.headroom_eur),
            "headroom_status": self.headroom_status,
            "vrt_200_eligibility": self.vrt_200_eligibility,
            "vrt_status": self.vrt_status,
            "customs_status": self.customs_status,
            "import_vat_status": self.import_vat_status,
            "import_vat_cashflow_eur": _s(self.import_vat_cashflow_eur),
            "import_vat_economic_eur": _s(self.import_vat_economic_eur),
            "vat_recovery_posture": self.vat_recovery_posture,
            "tariff_status": self.tariff_status,
            "candidate_cn_code": self.candidate_cn_code,
            "blockers": list(self.blockers),
            "diligence": list(self.diligence),
        }


def customs_value_eur(*, hammer_eur: Decimal | None, transport_eur: Decimal | None, insurance_eur: Decimal | None) -> Decimal | None:
    if hammer_eur is None or transport_eur is None or insurance_eur is None:
        return None
    return money(hammer_eur + transport_eur + insurance_eur)


def import_vat_on(customs_value: Decimal, duty: Decimal) -> Decimal:
    return money((customs_value + duty) * VAT_RATE)


def economic_import_vat(cashflow: Decimal | None, posture: str) -> Decimal | None:
    if cashflow is None:
        return None
    if posture == "RECOVERABLE_CONFIRMED":
        return _ZERO
    return cashflow


def assess_landed(
    *,
    provenance: str,
    pre_tax_ceiling_eur: Decimal | None,
    current_bid_eur: Decimal | None = None,
    ni_clear_proven: bool = False,
    preferential_origin_proven: bool = False,
    duty_rate: Decimal | None = None,
    vrt_eur: Decimal | None = None,
    vrt_confirmed: bool = False,
    homologation_present: bool = False,
    registration_eur: Decimal | None = None,
    transport_eur: Decimal | None = None,
    insurance_eur: Decimal | None = None,
    vat_recovery_posture: str = "UNKNOWN",
    owner_vat_registered: bool = False,
) -> LandedView:
    del owner_vat_registered
    blockers: list[str] = []
    vrt_eligibility = "UNKNOWN"
    if not homologation_present:
        blockers.append("VRT homologation (EU category, seats, mass in service, TPMLM)")
    elif vrt_confirmed and vrt_eur == Decimal("200"):
        vrt_eligibility = "CONFIRMED"
    vrt_status = "CONFIRMED" if vrt_confirmed and vrt_eur is not None else "UNKNOWN"
    if vrt_status != "CONFIRMED":
        blockers.append("Official VRT")

    ni_hammer = pre_tax_ceiling_eur if ni_clear_proven and vrt_confirmed else None
    pref_hammer = None
    duty_hammer = None
    customs_status = "TARIFF_CLASSIFICATION_REQUIRED"
    import_status = "UNKNOWN"
    cashflow = None
    economic = None
    clear = provenance in {"ROI_NATIVE", "NI_PRE_2021_PROVEN", "NI_POST_2020_IMPORT_PROVEN"} and ni_clear_proven
    if provenance in {"NI_PRE_2021_PROVEN", "NI_POST_2020_IMPORT_PROVEN"} and not ni_clear_proven:
        blockers.append("NI customs evidence is not proven")
    if clear:
        customs_status = "NOT_DUE"
        import_status = "NOT_DUE"
        cashflow = _ZERO
        economic = _ZERO
    elif provenance in {"GB_ORIGIN", "GB_TO_NI_UNPROVEN"}:
        if transport_eur is None or insurance_eur is None:
            blockers.append("Transport and insurance to the border")
        if preferential_origin_proven:
            customs_status = "PREFERENTIAL_ORIGIN"
            import_status = "DUE_23"
            base = customs_value_eur(hammer_eur=pre_tax_ceiling_eur, transport_eur=transport_eur, insurance_eur=insurance_eur)
            if base is not None and vrt_confirmed:
                cashflow = import_vat_on(base, _ZERO)
                economic = economic_import_vat(cashflow, vat_recovery_posture)
                pref_hammer = pre_tax_ceiling_eur
        elif duty_rate is not None:
            customs_status = "DUTY_RATE_SUPPLIED"
            import_status = "DUE_23"
            base = customs_value_eur(hammer_eur=pre_tax_ceiling_eur, transport_eur=transport_eur, insurance_eur=insurance_eur)
            if base is not None and vrt_confirmed:
                cashflow = import_vat_on(base, money(base * duty_rate))
                economic = economic_import_vat(cashflow, vat_recovery_posture)
                duty_hammer = pre_tax_ceiling_eur
        else:
            import_status = "BLOCKED_DUTY_UNKNOWN"
            blockers.append("CN/TARIC duty rate or proven preferential origin")
    else:
        blockers.append("Provenance is not a cleared NI or priced GB scenario")

    if vat_recovery_posture not in {"RECOVERABLE_CONFIRMED", "NON_RECOVERABLE"} and not clear:
        blockers.append("Import VAT deductibility")
    if registration_eur is None and not clear:
        blockers.append("Registration cost")

    final = None
    recoverable = vat_recovery_posture in {"RECOVERABLE_CONFIRMED", "NON_RECOVERABLE"}
    if clear and vrt_confirmed and registration_eur is not None and ni_hammer is not None:
        final = ni_hammer
    elif preferential_origin_proven and vrt_confirmed and registration_eur is not None and pref_hammer is not None and recoverable:
        final = pref_hammer
    elif duty_rate is not None and vrt_confirmed and registration_eur is not None and duty_hammer is not None and recoverable:
        final = duty_hammer

    if current_bid_eur is not None and final is not None:
        headroom, headroom_status = money(final - current_bid_eur), "KNOWN"
    else:
        headroom, headroom_status = None, "UNKNOWN"
    diligence = tuple(dict.fromkeys(blockers))
    return LandedView(
        provenance=provenance,
        pre_tax_hammer_ceiling_eur=pre_tax_ceiling_eur,
        ni_clear_max_hammer_eur=ni_hammer if clear else None,
        gb_preferential_max_hammer_eur=pref_hammer,
        gb_confirmed_duty_max_hammer_eur=duty_hammer,
        final_max_safe_hammer_eur=final,
        headroom_eur=headroom,
        headroom_status=headroom_status,
        vrt_200_eligibility=vrt_eligibility,
        vrt_status=vrt_status,
        customs_status=customs_status,
        import_vat_status=import_status,
        import_vat_cashflow_eur=cashflow,
        import_vat_economic_eur=economic,
        vat_recovery_posture=vat_recovery_posture,
        tariff_status=customs_status,
        candidate_cn_code="",
        blockers=diligence,
        diligence=diligence,
    )


def _s(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None
