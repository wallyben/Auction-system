"""Live market calls. Excluded from the standard suite."""

from __future__ import annotations

import os

import httpx
import pytest

from app.domains.vehicles.commoncrawl import CommonCrawlMarketEnricher
from app.domains.vehicles.market_provider import BraveMarketSearchProvider

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_brave_live_market_search() -> None:
    key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not key:
        pytest.skip("BRAVE_SEARCH_API_KEY is not set")
    async with httpx.AsyncClient(timeout=30) as client:
        found = await BraveMarketSearchProvider(client, api_key=key).search('site:donedeal.ie "Ford Transit Custom" "2018"')
    assert found.provider == "brave"


@pytest.mark.asyncio
async def test_commoncrawl_live_lookup() -> None:
    async with httpx.AsyncClient(timeout=40) as client:
        indexes = await CommonCrawlMarketEnricher(client).indexes()
    assert indexes


@pytest.mark.asyncio
async def test_autoza_live_market() -> None:
    pytest.skip("Autoza live refresh stays on the existing cv market job")
