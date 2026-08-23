"""eBay Marketplace Insights probe.

Browse client-credentials tokens almost never include sold-item entitlement.
This adapter records an honest LIVE/UNAVAILABLE result. It never invents sold prices.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.sold.provider import SoldEvidenceHit

INSIGHTS_URL = {
    "production": "https://api.ebay.com/buy/marketplace_insights/v1_beta/item_sales/search",
    "sandbox": "https://api.sandbox.ebay.com/buy/marketplace_insights/v1_beta/item_sales/search",
}
# Current first-party surface (name retained if eBay drops _beta):
INSIGHTS_URL_V1 = {
    "production": "https://api.ebay.com/buy/marketplace_insights/v1/item_sales/search",
    "sandbox": "https://api.sandbox.ebay.com/buy/marketplace_insights/v1/item_sales/search",
}


class EbayMarketplaceInsightsProvider:
    name = "ebay_marketplace_insights"
    classification = "REALIZED_SOLD"

    def __init__(self, token: str | None = None) -> None:
        self.token = token

    async def search_realised_sales(
        self, product: str, market: str, condition: str, *, limit: int = 20
    ) -> list[SoldEvidenceHit]:
        # Do not call this path without a proven 200 entitlement. Empty is correct.
        return []

    async def healthcheck(self) -> dict[str, object]:
        return await self.probe()

    async def freshness(self) -> datetime | None:
        return None

    async def probe(self, token: str | None = None) -> dict[str, Any]:
        env = settings.ebay_api_env
        urls = [INSIGHTS_URL[env], INSIGHTS_URL_V1[env]]
        bearer = token or self.token
        if not bearer:
            return {
                "provider": self.name,
                "available": False,
                "http_status": None,
                "classification": self.classification,
                "note": "No access token. Insights not probed.",
            }
        last: dict[str, Any] = {}
        for url in urls:
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    response = await client.get(
                        url,
                        params={"q": "sony a7 iv", "limit": "1"},
                        headers={
                            "Authorization": f"Bearer {bearer}",
                            "X-EBAY-C-MARKETPLACE-ID": settings.ebay_marketplace_list()[0],
                        },
                    )
            except httpx.HTTPError as exc:
                last = {
                    "provider": self.name,
                    "available": False,
                    "url_probed": url,
                    "error": type(exc).__name__,
                    "classification": self.classification,
                }
                continue
            body_excerpt = response.text[:180].replace("\n", " ")
            if "access_token" in body_excerpt:
                body_excerpt = "[redacted]"
            last = {
                "provider": self.name,
                "available": response.status_code == 200,
                "http_status": response.status_code,
                "url_probed": url,
                "classification": self.classification if response.status_code == 200 else "UNAVAILABLE",
                "body_excerpt": body_excerpt,
                "note": (
                    "Enterprise-gated sold-item API. HTTP 200 would be REALIZED_SOLD. "
                    "Anything else is not sold evidence."
                ),
            }
            if response.status_code == 200:
                return last
        return last
