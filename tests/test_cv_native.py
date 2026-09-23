"""Native Irish market evidence. Values stay withheld when the book is thin."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import httpx
import pytest

from app.domains.vehicles.calibration import compare_valuations
from app.domains.vehicles.enums import Fuel, ObservationStatus
from app.domains.vehicles.evaluate import evaluate_vehicle
from app.domains.vehicles.funnel import funnel_report
from app.domains.vehicles.ingest.autoza import apply_history, fetch_autoza, observations_from_search
from app.domains.vehicles.listing_state import derive_listing_states, status_for_new_observation
from app.domains.vehicles.market import MarketBook
from app.domains.vehicles.query_plan import plan_queries
from app.domains.vehicles.sources import enabled_live_fetchers, vehicle_sources
from tests.test_cv_engine import AS_OF, _book, _obs, golden


def test_autoza_is_the_default_free_fetcher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CV_AUTOZA", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("CV_DEALER_FEED_URLS", raising=False)
    assert enabled_live_fetchers() == ("autoza",)
    monkeypatch.setenv("CV_AUTOZA", "0")
    assert enabled_live_fetchers() == ()
    statuses = {source.source_id: source.status for source in vehicle_sources()}
    assert statuses["autoza"] == "LIVE_PUBLIC"
    assert statuses["cartell_motorcheck"] == "OPTIONAL_CALIBRATION"
    assert statuses["donedeal"] == "BLOCKED_POLICY"


def test_autoza_parser_keeps_vans_and_drops_passengers() -> None:
    payload = {
        "data": [
            {
                "id": "kangoo-1",
                "url": "https://autoza.ie/listing/kangoo-1",
                "make": "Renault",
                "model": "Kangoo",
                "variant": "ML19 DCI",
                "year": 2019,
                "price": 9800,
                "currency": "EUR",
                "mileage": 90000,
                "mileage_unit": "km",
                "fuel_type": "Diesel",
                "transmission": "Manual",
                "body_type": "VAN",
                "location": "Cork",
            },
            {
                "id": "golf-1",
                "make": "Volkswagen",
                "model": "Golf",
                "year": 2019,
                "price": 14000,
                "currency": "EUR",
                "mileage": 80000,
                "mileage_unit": "km",
                "fuel_type": "Petrol",
                "body_type": "VAN",
            },
            {
                "id": "ev-1",
                "make": "Renault",
                "model": "Kangoo",
                "variant": "ELECTRIC ZE",
                "year": 2020,
                "price": 11000,
                "currency": "GBP",
                "mileage": 20000,
                "mileage_unit": "km",
                "fuel_type": "Electric",
                "body_type": "VAN",
            },
        ],
        "meta": {"total": 3},
    }
    rows = observations_from_search(payload, observed_at=AS_OF)
    assert [row.listing_id for row in rows] == ["autoza:kangoo-1", "autoza:ev-1"]
    assert rows[0].asking_price_eur == Decimal("9800")
    assert rows[0].vat_presentation == "unknown"
    assert rows[0].registration is None
    assert rows[0].generation is None
    assert rows[1].asking_price_eur is None
    assert rows[1].native_currency == "GBP"
    assert rows[1].fuel is Fuel.ELECTRIC


@pytest.mark.asyncio
async def test_autoza_fetch_uses_the_documented_search() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/vehicles"
        assert request.url.params["body_type"] == "van"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "custom-1",
                        "url": "https://autoza.ie/listing/custom-1",
                        "make": "Ford",
                        "model": "Transit Custom",
                        "variant": "300 L1 H1",
                        "year": 2019,
                        "price": 18000,
                        "currency": "EUR",
                        "mileage": 100000,
                        "mileage_unit": "km",
                        "fuel_type": "Diesel",
                        "transmission": "Manual",
                        "body_type": "VAN",
                        "location": "Dublin",
                    }
                ],
                "meta": {"total": 1},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://autoza.ie") as client:
        fetched = await fetch_autoza(
            client,
            [{"make": "Ford", "model": "Transit Custom", "body_type": "van"}],
            observed_at=AS_OF,
            pause_seconds=0,
        )
    assert fetched.error == ""
    assert fetched.complete is True
    assert fetched.observations[0].model_family == "transit_custom"
    assert "autoza.ie/api" not in fetched.observations[0].url or fetched.observations[0].url.startswith("https://autoza.ie/listing/")


def test_query_plan_prefers_auction_stock() -> None:
    queries, cursor = plan_queries([("Ford", "Transit Custom")], cursor=0, budget=2)
    assert queries[0]["reason"] == "active_auction"
    assert queries[0]["model"] == "Transit Custom"
    assert len(queries) == 2
    assert cursor != 0 or queries[1]["reason"] == "common_family"


def test_price_increase_and_return_are_not_sales() -> None:
    first = _obs(1, observed_at=AS_OF - timedelta(days=4), asking_price_eur=Decimal("18000"))
    higher = _obs(
        1,
        observation_id="obs-up",
        observed_at=AS_OF - timedelta(days=1),
        asking_price_eur=Decimal("19000"),
        status=ObservationStatus.PRICE_INCREASED,
    )
    gone = _obs(2, observation_id="obs-gone", listing_id="ie-2", observed_at=AS_OF - timedelta(days=2), status=ObservationStatus.DISAPPEARED, asking_price_eur=None)
    back = _obs(2, observation_id="obs-back", listing_id="ie-2", observed_at=AS_OF, asking_price_eur=Decimal("17000"), status=ObservationStatus.RETURNED)
    states = {row.listing_id: row for row in derive_listing_states([first, higher, gone, back])}
    assert states["ie-1"].status == "PRICE_INCREASED"
    assert states["ie-2"].status == "RETURNED"
    assert states["ie-2"].inferred_sale is False
    assert status_for_new_observation([first], asking_price_eur=Decimal("19000")) is ObservationStatus.PRICE_INCREASED
    book = MarketBook()
    book.append(first)
    annotated = apply_history(book, [_obs(1, observation_id="obs-next", asking_price_eur=Decimal("17000"))])
    assert annotated[0].status is ObservationStatus.PRICE_REDUCED


def test_passenger_crew_fuel_generation_and_mileage_are_rejected() -> None:
    case = golden()
    case.book = _book(0)
    case.identity.generation = "second"
    case.book.append(_obs(1, listing_title="Ford Transit Custom Tourneo"))
    case.book.append(_obs(2, body="CREW"))
    case.book.append(_obs(3, fuel=Fuel.ELECTRIC))
    case.book.append(_obs(4, generation="first"))
    case.book.append(_obs(5, mileage_km=400000))
    case.book.append(_obs(6))
    result = evaluate_vehicle(case)
    reasons = " ".join(reason for row in result.valuation.rejected for reason in row.reasons)
    assert "Passenger" in reasons
    assert "crew" in reasons.lower() or "people-mover" in reasons.lower()
    assert "Fuel mismatch" in reasons
    assert "Generation mismatch" in reasons
    assert "Mileage too far" in reasons
    assert result.valuation.expected_achievable_eur is None


def test_vat_bases_are_not_mixed_and_unknown_caps_confidence() -> None:
    mixed = golden()
    mixed.book = _book(0)
    for index in range(6):
        mixed.book.append(_obs(index, vat_presentation="ex_vat", asking_price_eur=Decimal("10000")))
    for index in range(6, 12):
        mixed.book.append(_obs(index, vat_presentation="vat_inclusive", asking_price_eur=Decimal("12300")))
    mixed_result = evaluate_vehicle(mixed)
    assert mixed_result.valuation.vat_basis == "vat_inclusive_ie_23"
    assert mixed_result.valuation.market_asking_eur == Decimal("12300.00")

    unknown = golden()
    unknown.book = _book(0)
    for index in range(12):
        unknown.book.append(_obs(index, vat_presentation="unknown"))
    unknown_result = evaluate_vehicle(unknown)
    assert unknown_result.valuation.expected_achievable_eur is None
    assert unknown_result.state.value != "BUY_CANDIDATE"


def test_duplicate_registration_and_dealer_do_not_inflate_the_book() -> None:
    case = golden()
    case.book = _book(0)
    for index in range(8):
        case.book.append(_obs(index, registration="191D12345", dealer_name=""))
    case.book.append(_obs(20, registration="191D12345", source="autoza", listing_id="autoza-copy"))
    case.book.append(_obs(21, dealer_name="Cork Vans", listing_id="dealer-a"))
    case.book.append(_obs(22, dealer_name="Cork Vans", listing_id="dealer-b", source="autoza"))
    result = evaluate_vehicle(case)
    assert result.valuation.expected_achievable_eur is None
    rejected = " ".join(reason for row in result.valuation.rejected for reason in row.reasons)
    assert "Duplicate registration" in rejected
    assert "Same dealer" in rejected


def test_outlier_does_not_set_the_median_and_thin_book_withholds() -> None:
    case = golden()
    case.book = _book(0)
    for index in range(11):
        case.book.append(_obs(index, asking_price_eur=Decimal("18000")))
    case.book.append(_obs(30, asking_price_eur=Decimal("80000")))
    result = evaluate_vehicle(case)
    assert result.valuation.market_asking_eur == Decimal("18000.00")
    assert result.valuation.model_version == "arie-native-v2"
    from app.domains.vehicles.valuation import value_vehicle

    assert value_vehicle(case.identity, case.book, as_of=case.as_of).model_version == "arie-native-v1"
    assert result.valuation.effective_sample_size >= Decimal("11")

    thin = golden()
    thin.book = _book(2)
    withheld = evaluate_vehicle(thin)
    assert withheld.valuation.expected_achievable_eur is None
    assert withheld.valuation.quick_sale_eur is None
    assert withheld.state.value != "BUY_CANDIDATE"


def test_future_observation_is_invisible_and_stale_book_withholds() -> None:
    case = golden()
    case.book.append(_obs(90, observation_id="future", observed_at=AS_OF + timedelta(days=2), asking_price_eur=Decimal("1000")))
    result = evaluate_vehicle(case)
    assert result.valuation.market_asking_eur == Decimal("18000.00")

    stale = golden()
    stale.as_of = AS_OF + timedelta(days=20)
    stale_result = evaluate_vehicle(stale)
    assert stale_result.valuation.expected_achievable_eur is None
    assert stale_result.valuation.fresh is False


def test_catalogue_funnel_and_calibration_do_not_call_paid_providers() -> None:
    kept = evaluate_vehicle(golden())
    weak_case = golden()
    weak_case.book = _book(1)
    weak = evaluate_vehicle(weak_case)
    report = funnel_report([kept, weak])
    assert report["entered"] == 2
    assert report["shadow_candidates"] == 1
    point = compare_valuations(
        case_id="lot-1",
        native_eur=Decimal("8200"),
        provider="cartell",
        provider_eur=Decimal("8400"),
        recorded_at=AS_OF,
    )
    assert point["percentage_difference"] == "0.0244"
    assert point["trained"] is False


def test_camera_registry_is_unchanged() -> None:
    from app.sources.registry import all_adapters

    ids = {adapter.source_id for adapter in all_adapters()}
    assert "ebay_browse" in ids
    assert "autoza" not in ids
