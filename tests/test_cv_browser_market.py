"""Public-page harvester. No live marketplace and no Chromium."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domains.vehicles.browser_market.base import PageFetch
from app.domains.vehicles.browser_market.cache import load_cached, store_cached
from app.domains.vehicles.browser_market.carsireland import parse_carsireland
from app.domains.vehicles.browser_market.carzone import parse_carzone
from app.domains.vehicles.browser_market.challenge import detect_challenge, retryable
from app.domains.vehicles.browser_market.dealer_generic import parse_dealer
from app.domains.vehicles.browser_market.donedeal import parse_donedeal
from app.domains.vehicles.browser_market.harvest import harvest_market_group, select_enrichments
from app.domains.vehicles.browser_market.pagination import next_page_url, scroll_should_stop
from app.domains.vehicles.browser_market.playwright_runtime import BrowserSession, host_lock
from app.domains.vehicles.browser_market.urls import classify_market_url, result_urls
from app.domains.vehicles.browser_market.html_tree import parse_html
from app.domains.vehicles.market_search import group_for
from app.jobs.queue import PIPELINE_JOBS
from tests.fixtures.browser_market.pages import (
    CARSIRELAND_RESULTS,
    CARZONE_RESULTS,
    CHALLENGE_PAGE,
    DEALER_RESULTS,
    DONEDEAL_RESULTS,
    PAGINATION_PAGE,
)


def test_listing_url_classes() -> None:
    assert classify_market_url("https://www.donedeal.ie/vans?words=ford+transit") == "DONEDEAL_RESULTS"
    assert classify_market_url("https://www.donedeal.ie/vans-for-sale/ford-transit-custom-2018/39112233") == "DONEDEAL_LISTING"
    assert classify_market_url("https://www.carsireland.ie/used-cars?make=Ford") == "CARSIRELAND_RESULTS"
    assert classify_market_url("https://www.carsireland.ie/used-cars/peugeot/partner/88221100") == "CARSIRELAND_LISTING"
    assert classify_market_url("https://www.carzone.ie/used-cars?make=Opel") == "CARZONE_RESULTS"
    assert classify_market_url("https://www.carzone.ie/used-cars/opel/combo/77331122") == "CARZONE_LISTING"
    assert classify_market_url("https://harbourvans.ie/stock/ford-transit-2021-44119920") == "DEALER_LISTING"
    assert classify_market_url("https://www.donedeal.ie/vans") == "DONEDEAL_RESULTS"


def test_donedeal_cards_keep_full_price_and_drop_finance_and_crew() -> None:
    cards = parse_donedeal(DONEDEAL_RESULTS, "https://www.donedeal.ie/vans?words=ford")
    by_url = {card.url: card for card in cards}
    first = by_url["https://www.donedeal.ie/vans-for-sale/ford-transit-custom-2018/39112233"]
    assert first.asking_price_eur == Decimal("12950")
    assert first.vat_classification == "VAT_EXCLUSIVE"
    assert first.mileage_km == 84000
    assert first.geography == "ROI"
    second = by_url["https://www.donedeal.ie/vans-for-sale/ford-transit-custom-2019/39112234"]
    assert second.asking_price_eur == Decimal("15500")
    assert second.vat_classification == "VAT_INCLUSIVE"
    assert second.mileage_unit == "miles"
    crew = by_url["https://www.donedeal.ie/vans-for-sale/ford-transit-custom-crew/39112235"]
    assert crew.body == "CREW"
    deposit = by_url["https://www.donedeal.ie/vans-for-sale/ford-transit-custom-2018/39112236"]
    assert deposit.price_status != "PRICE_PLAUSIBLE"


def test_carsireland_and_carzone_and_dealer() -> None:
    ireland = parse_carsireland(CARSIRELAND_RESULTS, "https://www.carsireland.ie/used-cars?make=Peugeot")
    assert ireland[0].vat_classification == "NO_VAT"
    assert ireland[0].asking_price_eur == Decimal("14250")
    zone = parse_carzone(CARZONE_RESULTS, "https://www.carzone.ie/used-cars?make=Opel")
    assert zone[0].asking_price_eur == Decimal("11950")
    assert zone[0].dealer == "Harbour Vans Ltd"
    assert zone[0].geography == "ROI"
    dealer = parse_dealer(DEALER_RESULTS, "https://harbourvans.ie/vans")
    assert dealer[0].year == 2021
    assert dealer[0].listing_class == "DEALER_LISTING"


def test_challenge_and_pagination_and_scroll_stop() -> None:
    assert detect_challenge(403, CHALLENGE_PAGE) == "BLOCKED_CHALLENGE"
    assert detect_challenge(429, "<html>rate limit</html>") == "RATE_LIMITED"
    assert detect_challenge(200, "<html>log in to continue</html>") == "BLOCKED_LOGIN"
    assert detect_challenge(0, "") == "NAVIGATION_FAILED"
    assert retryable("BLOCKED_CHALLENGE", 403) is False
    assert retryable("NAVIGATION_FAILED", 0) is True
    root = parse_html(DONEDEAL_RESULTS)
    assert next_page_url(root, "https://www.donedeal.ie/vans?page=1").endswith("page=2")
    numbered = parse_html(PAGINATION_PAGE)
    assert "page=2" in next_page_url(numbered, "https://www.donedeal.ie/vans?page=1")
    assert scroll_should_stop([10, 10, 10]) is True
    assert scroll_should_stop([10, 12, 14]) is False
    assert scroll_should_stop([4, 4, 5, 5, 5], limit=3) is True


def test_browser_session_closes_without_launch() -> None:
    session = BrowserSession()
    session.close()
    session.close()
    assert session.closed is True
    assert host_lock("www.donedeal.ie") is host_lock("donedeal.ie")


def test_page_cap_challenge_and_enrichment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CV_BROWSER_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("CV_BROWSER_MAX_PAGES_PER_SOURCE_GROUP", "1")
    monkeypatch.setenv("CV_BROWSER_MAX_LISTING_ENRICHMENTS_PER_GROUP", "1")
    group = group_for("transit_custom", 2018, "PANEL", "DIESEL")
    assert group is not None
    calls: list[str] = []

    def fetch(url: str) -> PageFetch:
        calls.append(url)
        if "donedeal.ie" in url and "39112233" not in url:
            return PageFetch(url, url, 403, CHALLENGE_PAGE, challenge="BLOCKED_CHALLENGE")
        if "carsireland.ie" in url and "39112240" not in url:
            html = """
            <html><body><div>
              <a href="/used-cars/ford/transit-custom/39112240">Ford Transit Custom 2018 panel</a>
              <span>€13,200 + VAT</span><span>70,000 km Dublin</span>
            </div></body></html>
            """
            return PageFetch(url, "https://www.carsireland.ie/used-cars?make=Ford", 200, html)
        if "88221100" in url:
            return PageFetch(url, url, 200, CARSIRELAND_RESULTS.replace("42,000 km", "42,000 km VAT qualifying"))
        return PageFetch(url, url, 200, "<html><body>empty</body></html>")

    report = harvest_market_group(group, fetch, discovered={"browser-carzone-1": [], "browser-dealer-1": []}, delay_s=0)
    assert report.sources["browser-donedeal-1"].challenge == "BLOCKED_CHALLENGE"
    assert report.sources["browser-donedeal-1"].pages_opened == 1
    assert report.accepted >= 1
    assert any(row.geography == "ROI" for row in report.observations)
    cards = parse_carsireland(CARSIRELAND_RESULTS, "https://www.carsireland.ie/used-cars?make=Peugeot")
    cards[0].vat_classification = "VAT_UNKNOWN"
    cards[0].mileage_km = None
    chosen = select_enrichments(cards, limit=12)
    assert chosen and len(chosen) <= 12
    built = result_urls(group)
    assert built[0][0] == "browser-donedeal-1"
    assert "cv-browser-market-harvest" in PIPELINE_JOBS
    assert "cv-browser-listing-enrich" in PIPELINE_JOBS


def test_cache_avoids_a_second_fetch(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CV_BROWSER_STATE_DIR", str(tmp_path))
    group = group_for("partner", 2023)
    assert group is not None
    cards = parse_carsireland(CARSIRELAND_RESULTS, "https://www.carsireland.ie/used-cars?make=Peugeot")
    cached_url = "https://www.carsireland.ie/used-cars?make=Peugeot"
    store_cached("browser-carsireland-1", group.group_id, cached_url, cards)
    moment = datetime.now(timezone.utc)
    assert load_cached("browser-carsireland-1", group.group_id, cached_url, now=moment)
    monkeypatch.setattr(
        "app.domains.vehicles.browser_market.harvest.result_urls",
        lambda _group: [("browser-carsireland-1", cached_url)],
    )

    def fetch(url: str) -> PageFetch:
        raise AssertionError(url)

    report = harvest_market_group(group, fetch, delay_s=0, as_of=moment)
    assert report.pages_opened == 0
    assert report.raw_cards >= 1
