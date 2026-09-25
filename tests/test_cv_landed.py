"""Landed-cost scenarios, dealer diversity, and catalogue identity."""

from __future__ import annotations

from decimal import Decimal

from app.domains.vehicles.evidence import EvidenceLedger
from app.domains.vehicles.identity import parse_listing_text
from app.domains.vehicles.prebid_economics import assess_landed, customs_value_eur, economic_import_vat, import_vat_on
from app.domains.vehicles.provenance import ProvenanceInput, assess_provenance
from app.domains.vehicles.scenarios import prebid_economic_group
from app.domains.vehicles.tax import VAT_RATE, TaxInput, assess_tax
from app.domains.vehicles.enums import Fuel, ProvenanceState, RegistrationSignal
from app.domains.vehicles.identity import registration_signal
from app.domains.vehicles.valuation_v3 import value_vehicle_v3
from tests.test_cv_engine import _book, _obs, golden
from types import SimpleNamespace


def _screen(**kwargs: object) -> SimpleNamespace:
    base = dict(
        prebid_floor_available=True,
        market_floor_confidence="MEDIUM",
        max_hammer_vat_stress_eur=Decimal("5000"),
        max_hammer_market_floor_eur=Decimal("6000"),
        final_max_safe_hammer_eur=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_gb_unknown_duty_and_vrt_withhold_final_safe_hammer() -> None:
    view = assess_landed(provenance="GB_ORIGIN", pre_tax_ceiling_eur=Decimal("5000"), current_bid_eur=Decimal("1000"))
    assert view.final_max_safe_hammer_eur is None
    assert view.gb_confirmed_duty_max_hammer_eur is None
    assert view.pre_tax_hammer_ceiling_eur == Decimal("5000")
    assert view.pre_tax_hammer_ceiling_eur != view.final_max_safe_hammer_eur
    assert view.headroom_status == "UNKNOWN"
    assert view.tariff_status == "TARIFF_CLASSIFICATION_REQUIRED"
    assert prebid_economic_group(_screen()) == "ECONOMICALLY_INTERESTING_TAX_DILIGENCE"


def test_ni_clear_removes_duty_only_with_proof_and_plate_does_not() -> None:
    proven = assess_landed(
        provenance="NI_PRE_2021_PROVEN",
        pre_tax_ceiling_eur=Decimal("5000"),
        ni_clear_proven=True,
        vrt_confirmed=True,
        vrt_eur=Decimal("200"),
        homologation_present=True,
        registration_eur=Decimal("50"),
        current_bid_eur=Decimal("1000"),
    )
    assert proven.customs_status == "NOT_DUE"
    assert proven.import_vat_economic_eur == Decimal("0")
    assert proven.final_max_safe_hammer_eur == Decimal("5000")
    unproven = assess_landed(provenance="GB_TO_NI_UNPROVEN", pre_tax_ceiling_eur=Decimal("5000"), ni_clear_proven=False)
    assert unproven.final_max_safe_hammer_eur is None
    assert registration_signal("ABC 1234") is RegistrationSignal.NI_FORMAT_WEAK
    plate = assess_provenance(
        ProvenanceInput(registration_signal=RegistrationSignal.NI_FORMAT_WEAK, auction_country="NI"),
        EvidenceLedger(),
    )
    assert plate.customs_clear is False
    assert plate.state is not ProvenanceState.NI_PRE_2021_PROVEN


def test_import_vat_preferential_and_unresolved_tariff() -> None:
    assert import_vat_on(Decimal("10000"), Decimal("1000")) == (Decimal("11000") * VAT_RATE).quantize(Decimal("0.01"))
    assert customs_value_eur(hammer_eur=Decimal("10000"), transport_eur=None, insurance_eur=Decimal("0")) is None
    preferential = assess_landed(
        provenance="GB_ORIGIN",
        pre_tax_ceiling_eur=Decimal("8000"),
        preferential_origin_proven=True,
        transport_eur=Decimal("200"),
        insurance_eur=Decimal("50"),
        vrt_confirmed=True,
        vrt_eur=Decimal("400"),
        registration_eur=Decimal("60"),
        vat_recovery_posture="NON_RECOVERABLE",
    )
    assert preferential.gb_preferential_max_hammer_eur == Decimal("8000")
    assert preferential.import_vat_cashflow_eur is not None
    assert preferential.final_max_safe_hammer_eur == Decimal("8000")
    blocked = assess_landed(provenance="GB_ORIGIN", pre_tax_ceiling_eur=Decimal("8000"), duty_rate=None)
    assert blocked.gb_confirmed_duty_max_hammer_eur is None
    assert blocked.final_max_safe_hammer_eur is None


def test_postponed_accounting_and_vrt_are_not_assumed() -> None:
    cash = Decimal("2300")
    assert economic_import_vat(cash, "UNKNOWN") == cash
    assert economic_import_vat(cash, "RECOVERABLE_CONFIRMED") == Decimal("0")
    registered = assess_landed(
        provenance="GB_ORIGIN",
        pre_tax_ceiling_eur=Decimal("8000"),
        preferential_origin_proven=True,
        transport_eur=Decimal("100"),
        insurance_eur=Decimal("0"),
        vrt_confirmed=True,
        vrt_eur=Decimal("200"),
        registration_eur=Decimal("50"),
        owner_vat_registered=True,
        vat_recovery_posture="UNKNOWN",
    )
    assert registered.final_max_safe_hammer_eur is None
    assert registered.vrt_200_eligibility == "UNKNOWN"
    tax = assess_tax(TaxInput(provenance=ProvenanceState.GB_ORIGIN, fuel=Fuel.DIESEL), EvidenceLedger())
    assert tax.vrt_eur is None
    assert tax.blocked is True


def test_robust_requires_a_resolved_hammer() -> None:
    assert prebid_economic_group(_screen(final_max_safe_hammer_eur=Decimal("4000"))) == "ROBUST_OPPORTUNITY"
    assert prebid_economic_group(_screen(final_max_safe_hammer_eur=Decimal("0"))) == "NO_ECONOMIC_HEADROOM"


def test_unknown_sellers_are_not_counted_as_two_dealers() -> None:
    case = golden()
    case.book = _book(0)
    for index in range(10):
        case.book.append(_obs(index, source="carzone", dealer_name="", mileage_km=80000 + index * 3000, vat_presentation="unknown", vat_classification="UNKNOWN", asking_price_eur=Decimal("10000")))
    result = value_vehicle_v3(case.identity, case.book, as_of=case.as_of)
    assert result.known_dealer_count == 0
    assert result.dealer_diversity_status != "DIVERSE_PROVEN"
    assert result.prebid_floor_available is True


def test_catalogue_identity_for_maxus_and_iveco() -> None:
    maxus = parse_listing_text("Maxus eDeliver 3 35kWh L1 H1 automatic electric van")
    daily = parse_listing_text("Iveco Daily 35S14 3520L 2.3 Hi-Matic high roof van")
    assert maxus.manufacturer == "maxus"
    assert maxus.model_family == "edeliver_3"
    assert daily.manufacturer == "iveco"
    assert daily.model_family == "daily"
