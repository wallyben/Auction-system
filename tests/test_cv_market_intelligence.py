"""DATA-006B retrieval, dedupe, archive, and risk mapping. No live network."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.domains.vehicles.capture import catalogue_to_cases
from app.domains.vehicles.commoncrawl import CommonCrawlMarketEnricher, _facts, _stamp
from app.domains.vehicles.enums import CheckOutcome, Fuel
from app.domains.vehicles.evaluate import listing_identity_sufficient
from app.domains.vehicles.market import MarketBook, MarketObservation
from app.domains.vehicles.market_dedupe import assign_duplicate_groups, primary_observations, seller_key
from app.domains.vehicles.market_extract import classify_listing_url, extract_listing
from app.domains.vehicles.market_harvest import harvest_group
from app.core.config import Settings
from app.core import config
from app.domains.vehicles.market_provider import BraveMarketSearchProvider, SearchBudget, SearchNotConfigured, brave_configured, source_health
from app.domains.vehicles.market_search import group_for, groups_for_lots, queries_for
from app.domains.vehicles.enums import ObservationStatus
from tests.test_cv_engine import AS_OF

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def test_query_uses_aliases_and_one_group_for_nearby_years() -> None:
    lots = [
        {"model_family": "transit_custom", "year": 2020, "body": "PANEL", "fuel": "DIESEL"},
        {"model_family": "transit_custom", "year": 2019, "body": "PANEL", "fuel": "DIESEL"},
        {"model_family": "transit_custom", "year": 2021, "body": "PANEL", "fuel": "DIESEL"},
    ]
    groups = groups_for_lots(lots)
    assert len(groups) <= 2
    combo = group_for("combo", 2020, "PANEL", "DIESEL")
    assert combo is not None
    texts = [row.text for row in queries_for(combo, "strategy-3")]
    assert any("Opel Combo" in text for text in texts)
    assert any("site:donedeal.ie" in text for text in texts)
    assert any("+ VAT" in text for text in texts)


def test_listing_url_classes_and_snippet_facts() -> None:
    assert classify_listing_url("https://www.donedeal.ie/commercials/ford-transit-custom/39112233") == "DONEDEAL_LISTING"
    assert classify_listing_url("https://www.donedeal.ie/commercials?words=transit") == "DONEDEAL_SEARCH_PAGE"
    assert classify_listing_url("https://www.carsireland.ie/used-cars/ford/transit/88221100") == "CARSIRELAND_LISTING"
    assert classify_listing_url("https://www.carzone.ie/search") == "CARZONE_SEARCH_PAGE"
    listing = extract_listing(
        "https://www.donedeal.ie/commercials/ford-transit-custom/39112233",
        "2018 Ford Transit Custom panel van",
        "Dublin dealer. €14,995 + VAT. 112,000 km.",
    )
    assert listing.rejection == ""
    assert listing.year == 2018
    assert listing.price_eur == Decimal("14995")
    assert listing.price_status == "PRICE_PLAUSIBLE"
    assert listing.price_evidence
    assert listing.mileage_km == 112000
    assert listing.mileage_evidence
    assert listing.vat_classification == "VAT_EXCLUSIVE"
    assert listing.geography == "ROI"
    finance = extract_listing(
        "https://www.carsireland.ie/used-cars/ford/transit/88221100",
        "2018 Ford Transit",
        "from €99 per week",
    )
    assert finance.price_status == "PRICE_NOT_FULL_ASKING"
    engine = extract_listing(
        "https://www.carzone.ie/used-cars/ford/transit-custom/fpa/44110022",
        "2019 Ford Transit Custom",
        "2.0 TDI €12,500 Dublin",
    )
    assert engine.mileage_km is None
    category = extract_listing(
        "https://www.donedeal.ie/commercials",
        "Ford vans",
        "€10,000 €12,000 €9,000",
    )
    assert category.rejection == "SEARCH_RESULT_NOT_A_LISTING"


def test_seller_and_cross_source_dedupe() -> None:
    assert seller_key("M3 Van Centre Ltd") == seller_key("M3 Vans")
    left = _row("a", "https://www.donedeal.ie/x/39112233", "m3", Decimal("14995"))
    right = _row("b", "https://www.carsireland.ie/y/88221100", "M3 Van Centre Limited", Decimal("15000"))
    grouped = assign_duplicate_groups([left, right])
    assert grouped[0].cross_source_duplicate_group_id == grouped[1].cross_source_duplicate_group_id
    assert len(primary_observations(grouped)) == 1


def test_budget_stops_and_cache_hits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "cv_search_max_requests_per_market_group", 1)
    budget = SearchBudget(tmp_path)
    assert budget.allow(group_id="g", auction_id="a")
    budget.record(group_id="g", auction_id="a")
    assert budget.allow(group_id="g", auction_id="a") is False
    assert budget.usage("a")["requests_for_auction"] == 1


def test_archive_timestamp_and_miss() -> None:
    stamp = _stamp("20260920120000")
    assert stamp is not None
    assert stamp.year == 2026
    title, facts = _facts('<html><title>Transit</title><script type="application/ld+json">{"name":"Transit","offers":{"price":"14995"}}</script></html>')
    assert title == "Transit"
    assert facts["price"] == "14995"


@pytest.mark.asyncio
async def test_archive_miss_and_brave_parse(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "index.commoncrawl.org" and request.url.path.endswith("collinfo.json"):
            return httpx.Response(200, json=[{"id": "CC-MAIN-2026-38"}])
        return httpx.Response(200, text="")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        capture = await CommonCrawlMarketEnricher(client).enrich("https://www.donedeal.ie/commercials/ford/39112233")
    assert capture.status == "ARCHIVE_MISS"
    payload = {
        "query": {"more_results_available": False},
        "web": {"results": [{"title": "Van", "url": "https://www.donedeal.ie/commercials/ford/39112233", "description": "€14,995 + VAT", "page_age": "2026-09-01T00:00:00Z", "extra_snippets": ["112,000 km"]}]},
    }

    seen: dict[str, str] = {}

    def brave(request: httpx.Request) -> httpx.Response:
        seen["country"] = request.url.params.get("country", "")
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(brave)) as client:
        found = await BraveMarketSearchProvider(client, api_key="test").search('site:donedeal.ie "Ford Transit Custom"')
    assert seen["country"] == "ALL"
    assert found.hits[0].page_age
    assert found.hits[0].extra_snippets == ("112,000 km",)
    async with httpx.AsyncClient(transport=httpx.MockTransport(brave)) as client:
        with pytest.raises(SearchNotConfigured):
            await BraveMarketSearchProvider(client, api_key="").search("x")


@pytest.mark.asyncio
async def test_harvest_accepts_roi_listing_and_records_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "brave_search_api_key", "test")
    monkeypatch.setattr(config.settings, "cv_common_crawl_enabled", False)
    monkeypatch.setattr(config.settings, "cv_market_search_enabled", True)
    group = group_for("transit_custom", 2018, "PANEL", "DIESEL")
    assert group is not None
    payload = {
        "query": {"more_results_available": False},
        "web": {
            "results": [
                {
                    "title": "2018 Ford Transit Custom panel van",
                    "url": "https://www.donedeal.ie/commercials/ford-transit-custom/39112233",
                    "description": "Dublin. €14,995 + VAT. 112,000 km.",
                    "page_age": "2026-09-20T00:00:00Z",
                    "extra_snippets": [],
                }
            ]
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    budget = SearchBudget(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        report = await harvest_group(group, client=client, budget=budget, auction_id="T426", strategies=("strategy-1",))
    assert report.search_requests >= 1
    assert report.accepted_observations >= 1
    assert report.observations[0].geography == "ROI"
    assert report.observations[0].source_type == "SEARCH_INDEX_CURRENT"
    assert budget.usage("T426")["requests_today"] >= 1


def test_missing_brave_key_is_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "brave_search_api_key", "")
    monkeypatch.setattr(config.settings, "cv_market_search_enabled", True)
    health = source_health()
    assert health["brave"]["status"] == "NOT_CONFIGURED"
    assert health["brave"]["configured"] is False
    assert health["autoza"]["status"] == "NOT_RUN"


def test_settings_env_file_configures_market_search_without_logging_the_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "unit-test-brave-token-not-a-real-key"
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                f"BRAVE_SEARCH_API_KEY={secret}",
                "CV_MARKET_SEARCH_ENABLED=true",
                "CV_COMMON_CRAWL_ENABLED=false",
                "CV_SEARCH_MAX_REQUESTS_PER_AUCTION=77",
                "CV_SEARCH_MAX_REQUESTS_PER_MARKET_GROUP=3",
                "CV_SEARCH_MARKET_CACHE_HOURS=6",
                "CV_SEARCH_MAX_REQUESTS_PER_DAY=9",
            ]
        ),
        encoding="utf-8",
    )
    loaded = Settings(_env_file=env_file)
    assert loaded.brave_search_api_key == secret
    assert loaded.cv_search_max_requests_per_auction == 77
    assert loaded.cv_common_crawl_enabled is False
    monkeypatch.setattr(config, "settings", loaded)
    assert brave_configured() is True
    health = source_health()
    assert health["brave"]["configured"] is True
    assert health["brave"]["status"] != "NOT_CONFIGURED"
    rendered = repr(health)
    assert secret not in rendered
    budget = SearchBudget(tmp_path / "state")
    assert budget.auction_cap == 77
    assert budget.group_cap == 3
    assert budget.day_cap == 9
    assert budget.cache_hours == 6
    empty = Settings(brave_search_api_key="")
    monkeypatch.setattr(config, "settings", empty)
    assert brave_configured() is False
    assert source_health()["brave"]["status"] == "NOT_CONFIGURED"


def test_cat_s_and_non_runner_enter_the_risk_gate() -> None:
    text = """
FORD TRANSIT CUSTOM PANEL VAN
Year 2018
Serial/Reg# 181D1234
Mileage/Clock 80000
KMS/Miles/Hrs Miles
Fuel Type Diesel
VCAR CAT S
Vendor Disclosure CAT S recorded
VAT Yes
Lot 3

VAUXHALL COMBO PANEL VAN
Year 2020
Serial/Reg# 201D999
Mileage/Clock 40000
KMS/Miles/Hrs Miles
Fuel Type Diesel
Vendor Disclosure Non-runner
VAT No
Lot 45
"""
    _parsed, cases = catalogue_to_cases(text, MarketBook(), as_of=AS_OF, fx_eur_per_gbp=Decimal("1.15"), fx_retrieved_at=AS_OF)
    by_lot = {case.listing.external_id: case for case in cases}
    cat = next(case for case in cases if case.history.write_off is not None)
    assert cat.history.write_off is not None
    assert cat.history.write_off.outcome is CheckOutcome.FAIL
    runner = next(case for case in cases if case.history.declared_faults)
    assert "non-runner" in runner.history.declared_faults
    assert listing_identity_sufficient(cat)
    del by_lot


def _row(observation_id: str, url: str, dealer: str, price: Decimal) -> MarketObservation:
    return MarketObservation(
        observation_id=observation_id,
        listing_id=observation_id,
        observed_at=NOW,
        manufacturer="ford",
        model_family="transit_custom",
        year=2018,
        fuel=Fuel.DIESEL,
        body="PANEL",
        wheelbase=None,
        roof=None,
        transmission=None,
        derivative=None,
        mileage_km=180000,
        generation=None,
        asking_price_eur=price,
        realised_price_eur=None,
        seller_type="dealer",
        vat_presentation="ex_vat",
        location="Dublin",
        status=ObservationStatus.ACTIVE,
        source="brave-donedeal-index-1",
        url=url,
        dealer_name=dealer,
        geography="ROI",
    )
