"""NI relief never cancels VRT, and an unknown tax line withholds the max bid."""

from decimal import Decimal

from app.domains.vehicles.auction_costs import AuctionFeeSchedule, PremiumBand, buyer_premium
from app.domains.vehicles.enums import EvidencePosture, Fuel, ProvenanceState
from app.domains.vehicles.evidence import EvidenceLedger
from app.domains.vehicles.owner_view import owner_quote
from app.domains.vehicles.tax import Homologation, TaxInput, assess_tax, category_b_co2_charge, ev_vrt_relief_cap_eur
from datetime import datetime, timezone


def _n1() -> Homologation:
    return Homologation("N1", 3, 2000, 2800, "CoC", "coc-1")


def _position(state: ProvenanceState, **kwargs):
    data = TaxInput(provenance=state, fuel=Fuel.DIESEL, homologation=_n1(), registration_fee_eur=Decimal("100"), registration_fee_posture=EvidencePosture.PROVEN, **kwargs)
    return assess_tax(data, EvidenceLedger())


def test_ni_import_declaration_zeros_import_tax_and_keeps_vrt() -> None:
    position = _position(ProvenanceState.NI_POST_2020_IMPORT_PROVEN)
    assert position.customs_duty_eur == 0
    assert position.import_vat_eur == 0
    assert position.vrt_eur == Decimal("200.00")


def test_ni_pre_2021_keeps_vrt() -> None:
    position = _position(ProvenanceState.NI_PRE_2021_PROVEN)
    assert position.customs_duty_eur == 0
    assert position.import_vat_eur == 0
    assert position.vrt_eur == Decimal("200.00")


def test_plate_alone_is_not_an_exemption() -> None:
    position = assess_tax(TaxInput(provenance=ProvenanceState.LIKELY_NI_NEEDS_DOCUMENTS, fuel=Fuel.DIESEL), EvidenceLedger())
    assert position.customs_duty_eur is None
    assert position.import_vat_eur is None


def test_gb_via_ni_without_proof_is_not_exempt() -> None:
    position = assess_tax(TaxInput(provenance=ProvenanceState.GB_TO_NI_UNPROVEN, fuel=Fuel.DIESEL, customs_value_eur=Decimal("10000")), EvidenceLedger())
    assert position.customs_duty_eur is None
    assert position.import_vat_eur is None


def test_proven_uk_origin_zeros_duty_and_keeps_import_vat() -> None:
    position = assess_tax(
        TaxInput(
            provenance=ProvenanceState.GB_ORIGIN,
            fuel=Fuel.DIESEL,
            customs_value_eur=Decimal("10000"),
            preferential_origin_proven=True,
            homologation=_n1(),
            registration_fee_eur=Decimal("100"),
            registration_fee_posture=EvidencePosture.PROVEN,
        ),
        EvidenceLedger(),
    )
    assert position.customs_duty_eur == 0
    assert position.import_vat_eur == Decimal("2300.00")
    assert position.vrt_eur == Decimal("200.00")


def test_category_b_rates_and_electric_mass() -> None:
    assert category_b_co2_charge(Decimal("10000"), Decimal("100")) == Decimal("800.00")
    assert category_b_co2_charge(Decimal("10000"), Decimal("140")) == Decimal("1330.00")
    from app.domains.vehicles.tax import _flat_200_ratio

    assert _flat_200_ratio(Fuel.ELECTRIC, 2000, 2501) is True
    assert _flat_200_ratio(Fuel.DIESEL, 2000, 2501) is False
    assert ev_vrt_relief_cap_eur(electric=True) == Decimal("5000")
    assert ev_vrt_relief_cap_eur(electric=False) is None
    assert ev_vrt_relief_cap_eur(electric=True, before_deadline=False) is None


def test_unproven_tax_still_produces_a_conservative_max_bid() -> None:
    quote = owner_quote(
        {
            "prebid_group": "ECONOMICALLY_INTERESTING_TAX_DILIGENCE",
            "provenance_status": "LIKELY_NI_NEEDS_DOCUMENTS",
            "valuation": {"expected_achievable_eur": "16000"},
            "economics": {"pre_tax_hammer_ceiling_eur": "6800", "final_max_safe_hammer_eur": None, "vrt_status": "UNKNOWN"},
        },
        fx="1.16",
        registration="UGZ 3040",
    )
    assert quote["max_bid_known"] is True
    assert quote["max_bid_gbp"]
    assert quote["alt_max_bid_gbp"]
    assert quote["sell_eur"] == "16000"


def test_reverse_premium_matches_the_band() -> None:
    schedule = AuctionFeeSchedule(
        schedule_id="t",
        source_id="t",
        version="1",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        evidence_url="catalogue",
        applies_to="commercial_vehicles",
        bands=(PremiumBand(Decimal("5000"), Decimal("0"), Decimal("300")),),
        minimum_premium_eur=Decimal("0"),
        premium_vat_rate=Decimal("0.20"),
        documentation_fee_eur=Decimal("0"),
        online_bidding_fee_eur=Decimal("0"),
        collection_fee_eur=Decimal("0"),
    )
    premium = buyer_premium(schedule, Decimal("4500"))
    vat = (premium * Decimal("0.20")).quantize(Decimal("0.01"))
    assert premium == Decimal("300.00")
    assert premium + vat == Decimal("360.00")
