"""Live public search pages. Excluded from the standard suite.

Set CV_BROWSER_LIVE=1 and install Chromium before running.
"""

from __future__ import annotations

import os

import pytest

from app.domains.vehicles.browser_market.carsireland import parse_carsireland
from app.domains.vehicles.browser_market.carzone import parse_carzone
from app.domains.vehicles.browser_market.donedeal import parse_donedeal
from app.domains.vehicles.browser_market.playwright_runtime import browser_session, fetch_with_retry
from app.domains.vehicles.browser_market.urls import result_urls
from app.domains.vehicles.market_search import group_for

pytestmark = pytest.mark.live


def _live(url: str, parser):
    if os.environ.get("CV_BROWSER_LIVE") != "1":
        pytest.skip("CV_BROWSER_LIVE is not set")
    with browser_session(timeout_ms=30000) as session:
        fetched = fetch_with_retry(session, url)
    cards = parser(fetched.html, fetched.final_url or url) if not fetched.challenge else []
    return fetched, cards


def test_donedeal_browser_live() -> None:
    group = group_for("transit_custom", 2018)
    assert group is not None
    url = result_urls(group)[0][1]
    fetched, cards = _live(url, parse_donedeal)
    assert fetched.challenge in {"", "BLOCKED_CHALLENGE", "BLOCKED_LOGIN", "RATE_LIMITED", "NAVIGATION_FAILED"}
    if not fetched.challenge:
        assert cards


def test_carsireland_browser_live() -> None:
    group = group_for("partner", 2023)
    assert group is not None
    url = result_urls(group)[1][1]
    fetched, cards = _live(url, parse_carsireland)
    assert fetched.status_code or fetched.challenge
    if not fetched.challenge:
        assert cards


def test_carzone_browser_live() -> None:
    group = group_for("combo", 2020)
    assert group is not None
    url = result_urls(group)[2][1]
    fetched, cards = _live(url, parse_carzone)
    assert fetched.status_code or fetched.challenge
    if not fetched.challenge:
        assert cards
