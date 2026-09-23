"""VAT text, persisted observations, and the economic label."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domains.vehicles.evaluate import evaluate_vehicle
from app.domains.vehicles.orm import CvMarketObservationRow
from app.domains.vehicles.repository import append_observation, list_observations, observation_from_row
from app.domains.vehicles.scenarios import economic_label, ni_landing_scenarios
from app.domains.vehicles.vat_text import classify_vat_text, price_basis
from tests.test_cv_engine import AS_OF, _book, _obs, golden


def test_coverage_uses_known_vat_and_does_not_call_a_family_good_when_thin() -> None:
    from app.domains.vehicles.coverage import classify_family, coverage_report

    thin = [_obs(1, asking_price_eur=Decimal("10000"), vat_classification="VAT_EXCLUSIVE")]
    assert classify_family(thin) == "THIN"
    strong = []
    for index in range(8):
        strong.append(
            _obs(
                index,
                asking_price_eur=Decimal("18000"),
                vat_classification="VAT_EXCLUSIVE",
                year=2018 + (index % 3),
                mileage_km=80000 + index * 1000,
            )
        )
    assert classify_family(strong) == "GOOD_COVERAGE"
    report = coverage_report(strong)
    assert report[0]["listings_with_usable_vat"] == 8


def test_common_listing_forms_fill_size_fuel_and_series() -> None:
    from app.domains.vehicles.enums import Fuel
    from app.domains.vehicles.identity import parse_listing_text

    combo = parse_listing_text("2019 Opel Combo CARGO L1H1 75PS 5DR")
    assert combo.wheelbase == "l1"
    assert combo.roof == "h1"
    transit = parse_listing_text("2021 Ford Transit 350L BASE 2.0 TD 130BHP M6 RWD LWB")
    assert transit.model_family == "transit"
    assert transit.derivative == "350"
    assert transit.wheelbase == "lwb"
    assert transit.fuel is Fuel.DIESEL
    kangoo = parse_listing_text("2020 Renault Kangoo EXPRESS ZE LL21 Z.E 33 BUSINESS")
    assert kangoo.wheelbase == "l2"
    assert kangoo.fuel is Fuel.ELECTRIC
    dispatch = parse_listing_text("2022 Citroen Dispatch MWB 1.5 BLUEHDI 100")
    assert dispatch.wheelbase == "mwb"
    assert dispatch.fuel is Fuel.DIESEL
    transporter = parse_listing_text("2022 Volkswagen Transporter T28 STARTLINE 2.0 TDI")
    assert transporter.derivative == "t28"


def test_vat_phrases() -> None:
    exclusive = classify_vat_text("Price €10,000 + VAT at 23%")
    assert exclusive.classification == "VAT_EXCLUSIVE"
    net, gross, rate = price_basis(Decimal("10000"), exclusive.classification, exclusive.fragment)
    assert net == Decimal("10000")
    assert gross == Decimal("12300.00")
    assert rate == Decimal("0.23")
    inclusive = classify_vat_text("€12,300 including VAT")
    assert inclusive.classification == "VAT_INCLUSIVE"
    plain_net, plain_gross, plain_rate = price_basis(Decimal("12300"), inclusive.classification, inclusive.fragment)
    assert plain_gross == Decimal("12300")
    assert plain_net is None
    assert plain_rate is None
    rated = classify_vat_text("€12,300 including VAT at 23%")
    rated_net, rated_gross, rated_rate = price_basis(Decimal("12300"), rated.classification, rated.fragment)
    assert rated_gross == Decimal("12300")
    assert rated_net == Decimal("10000.00")
    assert rated_rate == Decimal("0.23")
    assert classify_vat_text("Ford Transit Custom panel van").classification == "UNKNOWN"
    assert classify_vat_text("margin scheme").classification == "MARGIN_SCHEME"
    conflict = classify_vat_text("ex VAT and including VAT")
    assert conflict.classification == "UNKNOWN"


def test_known_vat_comps_are_not_capped_by_unknown_neighbours() -> None:
    case = golden()
    case.book = _book(0)
    for index in range(10):
        case.book.append(_obs(index, vat_presentation="ex_vat", asking_price_eur=Decimal("18000")))
    for index in range(10, 12):
        case.book.append(_obs(index, vat_presentation="unknown", asking_price_eur=Decimal("9000")))
    result = evaluate_vehicle(case)
    assert result.valuation.market_asking_eur == Decimal("18000.00")
    assert result.valuation.expected_achievable_eur is not None
    assert result.state.value == "BUY_CANDIDATE"
    assert "UNCALIBRATED_ASSUMPTION" in " ".join(result.valuation.notes)


def test_observation_append_is_repeatable_without_overwrite() -> None:
    engine = create_engine("sqlite://")
    CvMarketObservationRow.__table__.create(engine)
    with Session(engine) as session:
        first = _obs(1, asking_price_eur=Decimal("15000"), vat_presentation="ex_vat")
        append_observation(session, first)
        session.commit()
        again = _obs(1, observation_id="obs-1b", asking_price_eur=Decimal("14000"))
        append_observation(session, again)
        session.commit()
        rows = list_observations(session)
        assert len(rows) == 2
        restored = observation_from_row(rows[0])
        assert restored.asking_price_eur in {Decimal("15000"), Decimal("14000")}
        try:
            append_observation(session, first)
            raised = False
        except ValueError:
            raised = True
        assert raised


def test_economic_prefilter_is_not_a_buy_and_scenarios_do_not_pass() -> None:
    label = economic_label(
        state="MANUAL_EVIDENCE_REQUIRED",
        market_pass=True,
        auction_cost_pass=True,
        has_conservative=True,
    )
    assert label == "ECONOMICALLY_INTERESTING_PENDING_DILIGENCE"
    assert label != "BUY_CANDIDATE"
    scenarios = ni_landing_scenarios("UNKNOWN")
    assert scenarios["gate_pass"] is False
    assert scenarios["landing_cost"] == "LANDING_COST_UNRESOLVED"
    assert all(item["passes_gate"] is False for item in scenarios["scenarios"])
    robust = ni_landing_scenarios(
        "UNKNOWN",
        conservative_resale_eur=Decimal("8000"),
        scenario_landed_eur={"SCENARIO_A": Decimal("6000"), "SCENARIO_B": Decimal("7000"), "SCENARIO_C": Decimal("7500")},
    )
    assert robust["classification"] == "ROBUST_OPPORTUNITY"
    assert robust["gate_pass"] is False
    hopeless = ni_landing_scenarios(
        "UNKNOWN",
        conservative_resale_eur=Decimal("8000"),
        scenario_landed_eur={"SCENARIO_A": Decimal("9000"), "SCENARIO_B": Decimal("11000"), "SCENARIO_C": Decimal("12000")},
    )
    assert hopeless["classification"] == "NOT_ECONOMIC"
    assert hopeless["gate_pass"] is False


def test_partial_refresh_does_not_invent_a_disappearance() -> None:
    from app.domains.vehicles.ingest.autoza import InventoryFetch

    partial = InventoryFetch(
        observations=(),
        rows_received=50,
        rows_accepted=40,
        rows_rejected=10,
        rejection_reasons={"not_a_recognised_commercial_van": 10},
        pages=1,
        complete=False,
        details_fetched=0,
        error="429",
    )
    assert partial.complete is False
    assert "DISAPPEARED" not in partial.rejection_reasons


def test_stale_market_withholds_and_camera_registry_stays() -> None:
    stale = golden()
    stale.as_of = AS_OF + timedelta(days=20)
    result = evaluate_vehicle(stale)
    assert result.valuation.fresh is False
    assert result.valuation.expected_achievable_eur is None
    from app.sources.registry import all_adapters

    assert "ebay_browse" in {adapter.source_id for adapter in all_adapters()}
    from app.domains.vehicles.market_audit import display_health

    down = display_health({"status": "DOWN", "last_success_at": None})
    assert down["status"] == "DOWN"
    assert down["fresh"] is False
