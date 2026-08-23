"""Live network proofs. These never certify a blocked source as LIVE."""

import pytest

from app.models.enums import SourceStatus
from app.sources.ecb import EcbFxAdapter
from app.sources.reverb import ReverbAdapter
from app.sources.scryfall import ScryfallAdapter

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_reverb_returns_real_listings() -> None:
    adapter = ReverbAdapter()
    proof = await adapter.healthcheck()
    # Reverb's public API is frequently 403 from datacentre IPs. That is a
    # real BLOCKED_TECHNICAL result, not a fake LIVE.
    if proof.status is SourceStatus.BLOCKED_TECHNICAL:
        assert proof.http_status in {403, 429, 401, None}
        return
    assert proof.status in {SourceStatus.LIVE, SourceStatus.DEGRADED}
    items = await adapter.search("sony a7", limit=3)
    assert items
    assert items[0].url.startswith("http")
    assert items[0].title
    assert items[0].asking_price is not None


@pytest.mark.asyncio
async def test_ecb_returns_gbp_rate() -> None:
    adapter = EcbFxAdapter()
    proof = await adapter.healthcheck()
    assert proof.ok
    rates, as_of = await adapter.fetch_rates()
    assert "GBP" in rates
    assert rates["GBP"] > 0
    assert as_of


@pytest.mark.asyncio
async def test_scryfall_returns_cardmarket_guide() -> None:
    adapter = ScryfallAdapter()
    proof = await adapter.healthcheck()
    assert proof.ok
    items = await adapter.search("sol ring", limit=1)
    assert items
    assert items[0].title


@pytest.mark.asyncio
async def test_ebay_sandbox_or_production_when_configured() -> None:
    from app.core.config import settings
    from app.sources.ebay import EbayBrowseAdapter

    adapter = EbayBrowseAdapter()
    if adapter._missing_credentials():
        pytest.skip("eBay credentials not configured")
    proof = await adapter.healthcheck()
    assert proof.status in {SourceStatus.LIVE, SourceStatus.DEGRADED}
    assert proof.http_status == 200
    items = await adapter.search("iphone", limit=2)
    if items:
        assert items[0].title
        assert items[0].url
        assert items[0].source_id == "ebay_browse"
    # Sandbox dummy inventory must never be treated as production sold evidence.
    if settings.ebay_api_env == "sandbox":
        assert proof.proof.get("env") == "sandbox"
