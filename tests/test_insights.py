from app.sold.insights import INSIGHTS_URL, EbayMarketplaceInsightsProvider


def test_insights_uses_only_official_v1_beta() -> None:
    assert "v1_beta" in INSIGHTS_URL["production"]
    assert "marketplace_insights/v1/" not in INSIGHTS_URL["production"]
    assert not hasattr(EbayMarketplaceInsightsProvider, "INSIGHTS_URL_V1")


def test_insights_search_empty_when_not_entitled() -> None:
    import asyncio

    provider = EbayMarketplaceInsightsProvider(token="dummy")
    provider._entitled = False
    hits = asyncio.run(provider.search_realised_sales("Sony A7 IV", "EBAY_IE", "used"))
    assert hits == []
