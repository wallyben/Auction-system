"""ARIE-CV fail-closed behaviour. Unknown must not become a buy candidate."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domains.vehicles.auction_costs import AuctionFeeSchedule, PremiumBand, buyer_premium
from app.domains.vehicles.backtest import evaluate_as_of
from app.domains.vehicles.board import clear, view
from app.domains.vehicles.cases import VehicleCase
from app.domains.vehicles.enums import (
    AuctionVatTreatment,
    BodyKind,
    CandidateState,
    CheckOutcome,
    Co2Basis,
    CommercialClass,
    EvidencePosture,
    Fuel,
    ObservationStatus,
    ProvenanceState,
    VrtState,
)
from app.domains.vehicles.evaluate import evaluate_vehicle, rank_candidates
from app.domains.vehicles.history import HistoryInput, OdometerReading, clear_check
from app.domains.vehicles.identity import (
    ListingIdentity,
    VehicleIdentity,
    detect_reappearances,
    parse_listing_text,
    registration_signal,
)
from app.domains.vehicles.identity import Appearance
from app.domains.vehicles.market import MarketBook, MarketObservation
from app.domains.vehicles.orm import CvMarketObservationRow
from app.domains.vehicles.provenance import HistoryPoint, KeeperEvidence, ProvenanceInput
from app.domains.vehicles.repository import append_observation, list_family
from app.domains.vehicles.sources import enabled_live_fetchers, vehicle_sources
from app.domains.vehicles.tax import Homologation, TaxInput, assess_tax, nox_charge_eur
from app.domains.vehicles.evidence import EvidenceLedger
from app.domains.vehicles.enums import RegistrationSignal

AS_OF = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
VIN = "WF0ABCDEFGH12345"


def _schedule(percent: str = "0.10") -> AuctionFeeSchedule:
    return AuctionFeeSchedule(
        schedule_id="fixture-commercial",
        source_id="fixture",
        version="v1",
        effective_from=AS_OF,
        retrieved_at=AS_OF,
        evidence_url="fixture://fees",
        applies_to="commercial_vehicles",
        bands=(PremiumBand(up_to_eur=None, percent=Decimal(percent)),),
        minimum_premium_eur=Decimal("10"),
        premium_vat_rate=Decimal("0.23"),
        documentation_fee_eur=Decimal("0"),
        online_bidding_fee_eur=Decimal("0"),
        collection_fee_eur=Decimal("0"),
    )


def _obs(index: int, **overrides: object) -> MarketObservation:
    payload: dict[str, object] = {
        "observation_id": f"obs-{index}",
        "listing_id": f"ie-{index}",
        "observed_at": AS_OF - timedelta(hours=20),
        "manufacturer": "ford",
        "model_family": "transit_custom",
        "year": 2019,
        "fuel": Fuel.DIESEL,
        "body": "PANEL",
        "wheelbase": "l1",
        "roof": "h1",
        "transmission": "manual",
        "derivative": "300",
        "mileage_km": 100000,
        "generation": None,
        "asking_price_eur": Decimal("18000"),
        "realised_price_eur": None,
        "seller_type": "dealer",
        "vat_presentation": "ex_vat",
        "location": "Dublin",
        "status": ObservationStatus.ACTIVE,
        "source": "owner_capture",
    }
    payload.update(overrides)
    return MarketObservation(**payload)  # type: ignore[arg-type]


def _book(count: int = 12) -> MarketBook:
    book = MarketBook()
    for index in range(count):
        book.append(_obs(index))
    return book


def _identity(**overrides: object) -> VehicleIdentity:
    identity = VehicleIdentity(
        manufacturer="ford",
        model_family="transit_custom",
        body=BodyKind.PANEL,
        wheelbase="l1",
        roof="h1",
        fuel=Fuel.DIESEL,
        transmission="manual",
        derivative="300",
        year=2019,
        vin=VIN,
        mileage_km=100000,
        commercial_class=CommercialClass.UNKNOWN,
    )
    for key, value in overrides.items():
        setattr(identity, key, value)
    return identity


def _clear(name: str) -> object:
    return clear_check(name, "history-fixture", f"{name}-ref", "The fixture source establishes this result.", AS_OF)


def golden(bid: str = "7000") -> VehicleCase:
    return VehicleCase(
        listing=ListingIdentity(
            source_id="cv_manual",
            external_id="lot-1",
            title="2019 Ford Transit Custom panel van",
            currency="EUR",
            current_bid=Decimal(bid),
        ),
        identity=_identity(),
        as_of=AS_OF,
        provenance=ProvenanceInput(
            irish_registration_certificate=True,
            irish_registration_reference="VRC-1",
            vehicle_vin=VIN,
            auction_country="IE",
        ),
        history=HistoryInput(
            listing_mileage_km=100000,
            readings=(
                OdometerReading(datetime(2024, 6, 1, tzinfo=timezone.utc), 80000, "nct", "nct-1"),
                OdometerReading(datetime(2025, 6, 1, tzinfo=timezone.utc), 95000, "nct", "nct-2"),
            ),
            stolen=_clear("stolen"),  # type: ignore[arg-type]
            finance=_clear("finance"),  # type: ignore[arg-type]
            write_off=_clear("write_off"),  # type: ignore[arg-type]
            keys=2,
        ),
        book=_book(),
        homologation=Homologation("N1", 3, 1900, 2800, "CoC", "COC-1"),
        schedule=_schedule(),
        vat_treatment=AuctionVatTreatment.NO_VAT,
        hammer_includes_vat=False,
        transport_eur=Decimal("250"),
        transport_posture=EvidencePosture.PROVEN,
        payment_fee_eur=Decimal("0"),
        payment_fee_posture=EvidencePosture.PROVEN,
        mechanical_inspected=True,
        fuel_override=Fuel.DIESEL,
    )


def test_shadow_candidate_survives_only_with_evidence() -> None:
    result = evaluate_vehicle(golden())
    assert result.state is CandidateState.BUY_CANDIDATE
    assert result.purchasing_recommendation is False
    assert result.certification.value == "SHADOW"
    assert result.bid.max_safe_hammer_eur is not None
    assert result.current_bid_eur is not None
    assert result.current_bid_eur <= result.bid.max_safe_hammer_eur
    assert result.tax.vrt_eur == Decimal("0.00")
    assert result.tax.import_vat_eur == Decimal("0.00")
    assert result.valuation.expected_achievable_eur != result.valuation.market_asking_eur
    assert result.valuation.quick_sale_eur is not None
    assert result.valuation.quick_sale_eur < result.valuation.expected_achievable_eur
    assert "does_not_bid" in result.to_dict()


def test_price_above_max_is_not_a_candidate() -> None:
    result = evaluate_vehicle(golden("50000"))
    assert result.state is CandidateState.PRICE_TOO_HIGH
    assert result.purchasing_recommendation is False


def test_berlingo_name_does_not_confirm_two_hundred_euro_vrt() -> None:
    case = golden()
    case.identity = parse_listing_text("Citroen Berlingo 1.6 HDi")
    case.identity.vin = "VF7BERLINGOVIN001"
    case.homologation = None
    case.provenance = ProvenanceInput(auction_country="NI", registration_signal=RegistrationSignal.NI_FORMAT_WEAK)
    result = evaluate_vehicle(case)
    assert result.state is not CandidateState.BUY_CANDIDATE
    assert result.tax.vrt_state is VrtState.VRT_REQUIRES_DATA
    assert result.tax.vrt_eur is None
    assert result.provenance.customs_clear is False


def test_ni_plate_with_gb_v5c_is_not_tax_clear() -> None:
    case = golden()
    case.provenance = ProvenanceInput(
        registration_signal=RegistrationSignal.NI_FORMAT_WEAK,
        auction_country="NI",
        v5c_original=KeeperEvidence("GB", "GB", "V5C"),
        vehicle_vin=VIN,
    )
    result = evaluate_vehicle(case)
    assert result.provenance.state in {ProvenanceState.GB_ORIGIN, ProvenanceState.GB_TO_NI_UNPROVEN}
    assert result.provenance.customs_clear is False
    assert result.tax.import_vat_eur is None
    assert result.state is not CandidateState.BUY_CANDIDATE


def test_flat_vrt_needs_homologation_and_a_strict_weight_ratio() -> None:
    ledger = EvidenceLedger()
    confirmed = assess_tax(
        TaxInput(
            provenance=ProvenanceState.NI_PRE_2021_PROVEN,
            fuel=Fuel.DIESEL,
            homologation=Homologation("N1", 3, 1900, 2800, "CoC", "COC-1"),
            registration_fee_eur=Decimal("100"),
            registration_fee_posture=EvidencePosture.PROVEN,
        ),
        ledger,
    )
    assert confirmed.vrt_state is VrtState.VRT_CONFIRMED
    assert confirmed.vrt_eur == Decimal("200.00")
    assert confirmed.nox_eur == Decimal("0.00")

    boundary = assess_tax(
        TaxInput(
            provenance=ProvenanceState.NI_PRE_2021_PROVEN,
            fuel=Fuel.DIESEL,
            homologation=Homologation("N1", 3, 2000, 2600, "CoC", "COC-2"),
            co2_g_per_km=None,
            registration_fee_eur=Decimal("100"),
            registration_fee_posture=EvidencePosture.PROVEN,
        ),
        EvidenceLedger(),
    )
    assert boundary.vrt_eur != Decimal("200.00")
    assert boundary.vrt_state is not VrtState.VRT_CONFIRMED

    electric = assess_tax(
        TaxInput(
            provenance=ProvenanceState.NI_POST_2020_IMPORT_PROVEN,
            fuel=Fuel.ELECTRIC,
            homologation=Homologation("N1", 2, 2000, 2501, "CoC", "COC-EV"),
            registration_fee_eur=Decimal("100"),
            registration_fee_posture=EvidencePosture.PROVEN,
        ),
        EvidenceLedger(),
    )
    assert electric.vrt_eur == Decimal("200.00")


def test_category_b_percentage_is_not_the_passenger_table() -> None:
    result = assess_tax(
        TaxInput(
            provenance=ProvenanceState.NI_PRE_2021_PROVEN,
            fuel=Fuel.DIESEL,
            homologation=Homologation("N1", 3, 2000, 2400, "CoC", "COC-B"),
            co2_g_per_km=Decimal("100"),
            co2_basis=Co2Basis.WLTP,
            omsp_eur=Decimal("10000"),
            omsp_source="revenue_omsp",
            registration_fee_eur=Decimal("80"),
            registration_fee_posture=EvidencePosture.PROVEN,
        ),
        EvidenceLedger(),
    )
    assert result.vrt_state is VrtState.VRT_CONFIRMED
    assert result.vrt_eur == Decimal("800.00")
    assert result.nox_eur == Decimal("0.00")


def test_nox_matches_revenue_worked_example_and_caps() -> None:
    assert nox_charge_eur(Decimal("120"), Fuel.DIESEL) == Decimal("1800.00")
    assert nox_charge_eur(Decimal("300"), Fuel.DIESEL) == Decimal("4850.00")
    assert nox_charge_eur(Decimal("120"), Fuel.PETROL) == Decimal("600.00")


def test_crew_van_is_not_a_panel_van_pass() -> None:
    case = golden()
    case.identity = _identity(body=BodyKind.CREW, seats=6)
    case.homologation = Homologation("N1", 6, 1900, 2800, "CoC", "CREW")
    result = evaluate_vehicle(case)
    assert result.gates.gates["COMMERCIAL_CLASS_PASS"] is False
    assert result.state is not CandidateState.BUY_CANDIDATE


def test_mileage_rollback_rejects() -> None:
    case = golden()
    case.history = HistoryInput(
        listing_mileage_km=40000,
        readings=(
            OdometerReading(datetime(2023, 1, 1, tzinfo=timezone.utc), 90000, "mot", "m1"),
            OdometerReading(datetime(2025, 1, 1, tzinfo=timezone.utc), 70000, "mot", "m2"),
        ),
        stolen=_clear("stolen"),  # type: ignore[arg-type]
        finance=_clear("finance"),  # type: ignore[arg-type]
        write_off=_clear("write_off"),  # type: ignore[arg-type]
    )
    result = evaluate_vehicle(case)
    assert result.history.mileage.outcome is CheckOutcome.FAIL
    assert result.state is CandidateState.REJECT


def test_unchecked_finance_is_not_a_pass() -> None:
    case = golden()
    case.history = replace(case.history, finance=None)
    result = evaluate_vehicle(case)
    assert result.gates.gates["HISTORY_PASS"] is False
    assert result.state is not CandidateState.BUY_CANDIDATE


def test_sibling_vans_are_not_comps_and_disappearance_is_not_a_sale() -> None:
    case = golden()
    case.book.append(
        _obs(90, observation_id="partner", listing_id="partner-1", manufacturer="peugeot", model_family="partner")
    )
    case.book.append(
        _obs(
            91,
            observation_id="gone",
            listing_id="gone-1",
            status=ObservationStatus.DISAPPEARED,
            asking_price_eur=Decimal("9000"),
        )
    )
    result = evaluate_vehicle(case)
    rejected_families = {row.model_family for row in result.valuation.rejected}
    assert "partner" in rejected_families
    assert all(row.model_family == "transit_custom" for row in result.valuation.comps)
    assert result.valuation.liquidity.disappeared_count >= 1
    assert result.state is CandidateState.BUY_CANDIDATE


def test_thin_market_and_stale_rules_fail_closed() -> None:
    thin = golden()
    thin.book = _book(3)
    assert evaluate_vehicle(thin).state is not CandidateState.BUY_CANDIDATE

    stale = golden()
    stale.as_of = datetime(2027, 6, 1, tzinfo=timezone.utc)
    refreshed = MarketBook()
    for index, row in enumerate(stale.book.observations):
        refreshed.append(_obs(index, observed_at=stale.as_of - timedelta(hours=5)))
    stale.book = refreshed
    result = evaluate_vehicle(stale)
    assert result.gates.gates["DATA_FRESHNESS_PASS"] is False
    assert result.state is not CandidateState.BUY_CANDIDATE


def test_gb_import_does_not_assume_ten_percent_duty() -> None:
    case = golden()
    case.provenance = ProvenanceInput(registration_signal=RegistrationSignal.GB_FORMAT, auction_country="GB")
    case.border_transport_eur = Decimal("400")
    case.insurance_eur = Decimal("50")
    case.registration_fee_eur = Decimal("150")
    case.registration_fee_posture = EvidencePosture.PROVEN
    unknown_duty = evaluate_vehicle(case)
    assert unknown_duty.provenance.state is ProvenanceState.GB_ORIGIN
    assert unknown_duty.gates.gates["PROVENANCE_PASS"] is True
    assert unknown_duty.tax.customs_duty_eur is None
    assert unknown_duty.tax.import_vat_eur is None
    assert unknown_duty.gates.gates["TAX_MODEL_PASS"] is False
    assert unknown_duty.state is not CandidateState.BUY_CANDIDATE

    case.preferential_origin_proven = True
    proven = evaluate_vehicle(case)
    assert proven.tax.customs_duty_eur == Decimal("0.00")
    assert proven.tax.import_vat_eur is not None
    assert proven.tax.import_vat_eur > 0
    assert proven.gates.gates["TAX_MODEL_PASS"] is True


def test_damaged_van_can_fail_the_downside_even_with_a_low_bid() -> None:
    case = golden("1000")
    case.history = replace(case.history, declared_faults=("accident damage", "structural corrosion"))
    result = evaluate_vehicle(case)
    assert result.repairs.downside_eur > result.repairs.expected_eur
    assert result.bid.max_safe_hammer_eur is not None
    assert result.bid.max_safe_hammer_eur < evaluate_vehicle(golden("1000")).bid.max_safe_hammer_eur


def test_higher_premium_lowers_the_maximum_bid() -> None:
    cheap = evaluate_vehicle(golden())
    dear = golden()
    dear.schedule = _schedule("0.18")
    other = evaluate_vehicle(dear)
    assert other.bid.max_safe_hammer_eur is not None
    assert cheap.bid.max_safe_hammer_eur is not None
    assert other.bid.max_safe_hammer_eur < cheap.bid.max_safe_hammer_eur


def test_tiered_premium_uses_the_whole_hammer_rate() -> None:
    schedule = AuctionFeeSchedule(
        schedule_id="tiers",
        source_id="fixture",
        version="v2",
        effective_from=AS_OF,
        retrieved_at=AS_OF,
        evidence_url="fixture://tiers",
        applies_to="commercial_vehicles",
        bands=(PremiumBand(Decimal("5000"), Decimal("0.15")), PremiumBand(None, Decimal("0.10"))),
        minimum_premium_eur=Decimal("10"),
        premium_vat_rate=Decimal("0.23"),
        documentation_fee_eur=Decimal("0"),
        online_bidding_fee_eur=Decimal("0"),
        collection_fee_eur=Decimal("0"),
    )
    assert buyer_premium(schedule, Decimal("4000")) == Decimal("600.00")
    assert buyer_premium(schedule, Decimal("8000")) == Decimal("800.00")


def test_future_comp_cannot_leak_into_a_backtest() -> None:
    case = golden()
    case.book.append(
        _obs(
            50,
            observation_id="future",
            listing_id="future-1",
            asking_price_eur=Decimal("40000"),
            observed_at=AS_OF + timedelta(days=30),
        )
    )
    blinded = evaluate_as_of(case, AS_OF)
    ids = {row.observation_id for row in blinded.valuation.comps}
    assert "future" not in ids


def test_reappearance_and_registration_signal() -> None:
    assert registration_signal("221D12345") is RegistrationSignal.IE_FORMAT
    assert registration_signal("AB12CDE") is RegistrationSignal.GB_FORMAT
    rows = detect_reappearances(
        [
            Appearance("vin:ABC", "wilsons:1", "wilsons", "1"),
            Appearance("vin:ABC", "bca:9", "bca", "9"),
        ]
    )
    assert rows[0]["count"] == 2


def test_identity_separates_transit_derivatives_and_passenger_cars() -> None:
    custom = parse_listing_text("2019 Ford Transit Custom 300 L1 H1 panel van 2.0 TDCI manual")
    assert custom.model_family == "transit_custom"
    assert custom.body is BodyKind.PANEL
    assert custom.fuel is Fuel.DIESEL
    connect = parse_listing_text("Ford Transit Connect Trend panel van")
    assert connect.model_family == "transit_connect"
    tourneo = parse_listing_text("Ford Tourneo Custom Titanium")
    assert tourneo.commercial_class is CommercialClass.PASSENGER
    golf = parse_listing_text("Volkswagen Golf 1.6 TDI")
    assert golf.commercial_class is CommercialClass.PASSENGER
    parts = parse_listing_text("Ford Transit Custom engine only")
    assert parts.commercial_class is CommercialClass.PARTS_OR_NOT_A_VEHICLE


def test_duplicate_observation_is_rejected_and_history_is_kept() -> None:
    engine = create_engine("sqlite://")
    CvMarketObservationRow.__table__.create(engine)
    with Session(engine) as session:
        first = _obs(1, asking_price_eur=Decimal("15000"))
        append_observation(session, first)
        session.commit()
        try:
            append_observation(session, first)
            raised = False
        except ValueError:
            raised = True
        assert raised
        append_observation(session, _obs(1, observation_id="obs-1b", asking_price_eur=Decimal("14000")))
        session.commit()
        rows = list_family(session, "transit_custom")
        assert [row.observation_id for row in rows] == ["obs-1", "obs-1b"]


def test_sources_do_not_fetch_and_are_independently_described(monkeypatch) -> None:
    monkeypatch.delenv("CV_AUTOZA", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("CV_DEALER_FEED_URLS", raising=False)
    assert enabled_live_fetchers() == ("autoza",)
    statuses = {source.source_id: source.status for source in vehicle_sources()}
    assert statuses["wilsons"] == "BLOCKED_POLICY"
    assert statuses["dvsa_mot"] == "BLOCKED_CREDENTIALS"
    assert statuses["donedeal"] == "BLOCKED_POLICY"
    assert statuses["autoza"] == "LIVE_PUBLIC"
    assert "LIVE" not in statuses.values()


def test_ranking_prefers_profit_and_liquidity() -> None:
    higher_bid = evaluate_vehicle(golden("8000"))
    lower_bid = evaluate_vehicle(golden("6900"))
    ordered = rank_candidates([higher_bid, lower_bid])
    assert ordered[0].current_bid_eur == Decimal("6900.00")
    assert ordered[0].expected_profit_at_current_eur > ordered[1].expected_profit_at_current_eur


def test_market_book_refuses_overwrite() -> None:
    book = MarketBook()
    book.append(_obs(1))
    try:
        book.append(_obs(1))
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_passenger_listing_is_rejected() -> None:
    case = golden()
    case.identity = parse_listing_text("Volkswagen Golf 1.6 TDI")
    result = evaluate_vehicle(case)
    assert result.state is CandidateState.REJECT


def test_copy_does_not_share_a_mutated_book() -> None:
    left = golden()
    right = deepcopy(golden())
    right.book.append(_obs(70, observation_id="extra", listing_id="extra"))
    assert len(left.book.observations) == 12
