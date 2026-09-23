"""Phase 2 acquisition, market book, and fail-closed behaviour."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domains.vehicles.auction_costs import AuctionFeeSchedule, PremiumBand, buyer_premium
from app.domains.vehicles.board import clear, remember, view
from app.domains.vehicles.capture import catalogue_to_cases
from app.domains.vehicles.certification_metrics import score_certification
from app.domains.vehicles.condition import observe_images
from app.domains.vehicles.enums import CandidateState, Fuel, ObservationStatus
from app.domains.vehicles.evaluate import evaluate_vehicle
from app.domains.vehicles.history_dvsa import dvsa_status, parse_mot_payload
from app.domains.vehicles.ingest.dealer_feed import parse_dealer_feed
from app.domains.vehicles.ingest.ebay_vans import observations_from_summaries
from app.domains.vehicles.ingest.mid_ulster import parse_catalogue
from app.domains.vehicles.listing_state import derive_listing_states
from app.domains.vehicles.market import MarketBook
from app.domains.vehicles.orm import CvEvaluationRow
from app.domains.vehicles.owner_documents import parse_owner_document
from app.domains.vehicles.runtime_book import add_observations, clear_book, current_book
from app.domains.vehicles.sources import enabled_live_fetchers
from app.domains.vehicles.store import load_evaluations, persist_evaluation
from tests.test_cv_engine import AS_OF, _book, _obs, golden

CATALOGUE = """
VANS, CARS, HGVs I T430
Ends Ending 01/10/2026 1:00 PM BST
BUYERS PREMIUM:
Cars, Vans & 4x4s:
£0 - £500 £75
£501 - £1,000 £100
£1,001 - £2,000 £175
£2,001 - £4,000 £250
£4,001 - PLUS £300
All Commission is plus VAT

FORD TRANSIT CUSTOM 300 L1 H1 2.0 ECOBLUE 130PS LOW ROOF VAN
Year 26/04/2019
Serial/Reg# YGZ 6189
Mileage/Clock 47353
KMS/Miles/Hrs Miles
Fuel Type Diesel
MOT/PSV 08/09/2026
Document Status Present
Vendor Disclosure Company Direct
Vendor Company Direct
VAT Yes
Buyers Premium Refer to 'Auction Information'
Lot 12
Current Bid £6400

HITACHI ZX130 EXCAVATOR
Year 01/01/2018
Lot 40
"""


def test_mid_ulster_catalogue_extracts_lot_fields_without_a_fetch() -> None:
    parsed = parse_catalogue(CATALOGUE)
    assert parsed.sale_code == "T430"
    assert parsed.closes_at is not None
    assert parsed.closes_at.hour == 13
    assert parsed.premium_vat_known is True
    assert parsed.premium_bands_gbp[-1] == (None, Decimal("300"))
    assert len(parsed.lots) == 2
    van = parsed.lots[0]
    assert van.lot_number == "12"
    assert van.registration == "YGZ 6189"
    assert van.year == 2019
    assert van.mileage_km == int(Decimal(47353) * Decimal("1.609344"))
    assert van.fuel is Fuel.DIESEL
    assert van.vat == "Yes"
    assert van.vendor == "Company Direct"
    assert van.document_status == "Present"
    assert van.mot_expiry == "08/09/2026"
    assert van.current_bid_gbp == Decimal("6400")
    _parsed, cases = catalogue_to_cases(
        CATALOGUE,
        MarketBook(),
        as_of=AS_OF,
        fx_eur_per_gbp=Decimal("1.17"),
        fx_retrieved_at=AS_OF,
    )
    assert len(cases) == 1
    assert cases[0].listing.source_id == "mid_ulster"
    assert cases[0].listing.ends_at is not None
    assert cases[0].schedule is not None
    result = evaluate_vehicle(cases[0])
    assert result.state is not CandidateState.BUY_CANDIDATE
    assert result.purchasing_recommendation is False


def test_fixed_premium_band_is_not_a_percentage() -> None:
    schedule = AuctionFeeSchedule(
        schedule_id="mua",
        source_id="mid_ulster",
        version="v",
        effective_from=AS_OF,
        retrieved_at=AS_OF,
        evidence_url="owner",
        applies_to="commercial_vehicles",
        bands=(
            PremiumBand(up_to_eur=Decimal("500"), percent=Decimal("0"), fixed_eur=Decimal("75")),
            PremiumBand(up_to_eur=None, percent=Decimal("0"), fixed_eur=Decimal("300")),
        ),
        minimum_premium_eur=Decimal("0"),
        premium_vat_rate=Decimal("0.20"),
        documentation_fee_eur=Decimal("0"),
        online_bidding_fee_eur=Decimal("0"),
        collection_fee_eur=Decimal("0"),
    )
    assert buyer_premium(schedule, Decimal("100")) == Decimal("75.00")
    assert buyer_premium(schedule, Decimal("8000")) == Decimal("300.00")


def test_listing_lifecycle_does_not_invent_a_sale() -> None:
    first = _obs(1, observed_at=AS_OF - timedelta(days=3), asking_price_eur=Decimal("18000"))
    reduced = _obs(
        1,
        observation_id="obs-1b",
        observed_at=AS_OF - timedelta(days=1),
        asking_price_eur=Decimal("17000"),
        status=ObservationStatus.PRICE_REDUCED,
    )
    gone = _obs(
        2,
        observation_id="obs-2",
        listing_id="ie-2",
        observed_at=AS_OF,
        status=ObservationStatus.DISAPPEARED,
        asking_price_eur=None,
    )
    states = {row.listing_id: row for row in derive_listing_states([first, reduced, gone])}
    assert states["ie-1"].status == "PRICE_REDUCED"
    assert states["ie-2"].status == "DISAPPEARED"
    assert states["ie-2"].inferred_sale is False


def test_comps_reject_generation_wheelbase_salvage_and_duplicates() -> None:
    case = golden()
    case.identity.generation = "second"
    case.book = _book(0)
    case.book.append(_obs(1, generation="first"))
    case.book.append(_obs(2, observation_id="wb", listing_id="wb", wheelbase="l2"))
    case.book.append(_obs(3, observation_id="salvage", listing_id="salvage", listing_title="Ford Transit Custom salvage damaged"))
    case.book.append(_obs(4, observation_id="ev", listing_id="ev", fuel=Fuel.ELECTRIC))
    case.book.append(_obs(5, observation_id="dup-a", listing_id="dup-a", registration="ABC123"))
    case.book.append(_obs(6, observation_id="dup-b", listing_id="dup-b", registration="ABC123"))
    result = evaluate_vehicle(case)
    reasons = " ".join(" ".join(row.reasons) for row in result.valuation.rejected)
    assert "Generation mismatch" in reasons
    assert "Wheelbase mismatch" in reasons
    assert "salvage" in reasons.lower() or "Damaged" in reasons
    assert "Duplicate registration" in reasons
    assert "Fuel mismatch" in reasons


def test_owner_text_cannot_pass_a_gate() -> None:
    try:
        parse_owner_document({"kind": "V5C", "reference": "note", "force_pass": True})
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_dealer_feed_appends_and_ebay_summary_skips_passenger_cars() -> None:
    clear_book()
    rows = parse_dealer_feed(
        "listing_id,manufacturer,model_family,year,fuel,body,asking_price_eur,mileage_km,seller_type,location\n"
        "dd-1,ford,transit_custom,2019,DIESEL,PANEL,18000,100000,dealer,Dublin\n",
        observed_at=AS_OF,
    )
    inserted, duplicates = add_observations(rows)
    assert inserted == 1
    assert duplicates == 0
    inserted_again, duplicates_again = add_observations(rows)
    assert inserted_again == 0
    assert duplicates_again == 1
    assert len(current_book().observations) == 1
    ebay = observations_from_summaries(
        [
            {
                "itemId": "1",
                "title": "2019 Ford Transit Custom panel van",
                "price": {"value": "15000", "currency": "EUR"},
                "itemWebUrl": "https://www.ebay.ie/itm/1",
            },
            {"itemId": "2", "title": "Volkswagen Golf 1.6 TDI", "price": {"value": "4000", "currency": "EUR"}},
        ],
        observed_at=AS_OF,
    )
    assert len(ebay) == 1
    assert ebay[0].model_family == "transit_custom"
    assert ebay[0].asking_price_eur == Decimal("15000")
    clear_book()


def test_history_and_images_stay_closed_without_credentials(monkeypatch) -> None:
    for name in ("DVSA_CLIENT_ID", "DVSA_CLIENT_SECRET", "DVSA_API_KEY", "DVSA_TOKEN_URL", "DVSA_SCOPE", "CV_CONDITION_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    status = dvsa_status()
    assert status["status"] == "BLOCKED_CREDENTIALS"
    assert "DVSA_API_KEY" in status["missing_env"]
    tests = parse_mot_payload(
        {"motTests": [{"completedDate": "2024-06-01T00:00:00+00:00", "testResult": "PASSED", "odometerValue": "80000", "odometerUnit": "mi"}]}
    )
    assert tests[0].jurisdiction is None
    assert observe_images(("https://example.test/van.jpg",)) == ()
    assert enabled_live_fetchers() == ()


def test_stale_candidate_is_downgraded_on_the_board() -> None:
    clear()
    result = evaluate_vehicle(golden())
    assert result.state is CandidateState.BUY_CANDIDATE
    result.evaluated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    remember(result)
    assert view("candidates") == []
    manual = view("manual")
    assert manual
    assert manual[0]["state"] == "MANUAL_EVIDENCE_REQUIRED"
    assert "downgraded" in manual[0]["why"].lower() or "Stale" in manual[0]["why"]
    clear()


def test_evaluation_round_trip_uses_postgres_shaped_rows() -> None:
    engine = create_engine("sqlite://")
    CvEvaluationRow.__table__.create(engine)
    result = evaluate_vehicle(golden())
    with Session(engine) as session:
        persist_evaluation(result, freeze_shadow=True, session=session)
        session.commit()
        rows = load_evaluations("candidates", session)
    assert rows[0]["state"] == "BUY_CANDIDATE"
    assert rows[0]["purchasing_recommendation"] is False


def test_certification_is_not_passed_with_an_empty_sample() -> None:
    report = score_certification(historical_cases=0, live_shadow_cases=0)
    assert report["posture"] == "NOT_STARTED"
    assert report["passed"] is False
    assert all(metric["passed"] is None for metric in report["metrics"])
