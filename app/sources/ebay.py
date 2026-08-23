"""eBay Browse API adapter. LIVE only with official OAuth client credentials."""

from __future__ import annotations

import base64
import time
from decimal import Decimal
from typing import Any

from app.core.config import settings
from app.core.http import build_client, request_json
from app.core.logging import get_logger
from app.models.enums import SourceKind, SourceStatus
from app.sources.base import HealthProof, NormalizedListing, SourceAdapter

logger = get_logger("arie.sources.ebay")

TOKEN_URL = {
    "production": "https://api.ebay.com/identity/v1/oauth2/token",
    "sandbox": "https://api.sandbox.ebay.com/identity/v1/oauth2/token",
}
SEARCH_URL = {
    "production": "https://api.ebay.com/buy/browse/v1/item_summary/search",
    "sandbox": "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search",
}


class EbayBrowseAdapter(SourceAdapter):
    source_id = "ebay_browse"
    display_name = "eBay Browse API"
    country = "IE"
    kind = SourceKind.ACQUISITION
    official_api = True
    access_method = "oauth_client_credentials"
    credentials_required = True
    cadence_minutes = 15

    def __init__(self) -> None:
        self._token: str | None = None

    def _missing_credentials(self) -> bool:
        return not settings.ebay_client_id or not settings.ebay_client_secret

    async def healthcheck(self) -> HealthProof:
        if self._missing_credentials():
            return HealthProof(
                status=SourceStatus.BLOCKED_CREDENTIALS,
                ok=False,
                http_status=None,
                latency_ms=None,
                records=0,
                detail="EBAY_CLIENT_ID / EBAY_CLIENT_SECRET not configured. Create an app at developer.ebay.com.",
                proof={"docs": "https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search"},
            )
        started = time.perf_counter()
        try:
            listings = await self.search("iphone", limit=1)
            return HealthProof(
                status=SourceStatus.LIVE if listings else SourceStatus.DEGRADED,
                ok=bool(listings),
                http_status=200,
                latency_ms=int((time.perf_counter() - started) * 1000),
                records=len(listings),
                detail="Browse search succeeded.",
                proof={"sample": listings[0].external_id if listings else None},
            )
        except Exception as exc:
            logger.warning("ebay_health_failed", error=str(exc))
            return HealthProof(
                status=SourceStatus.BLOCKED_TECHNICAL,
                ok=False,
                http_status=getattr(exc, "status_code", None),
                latency_ms=int((time.perf_counter() - started) * 1000),
                records=0,
                detail=str(exc),
                proof={},
            )

    async def _token_header(self) -> dict[str, str]:
        if self._token:
            return {"Authorization": f"Bearer {self._token}"}
        basic = base64.b64encode(
            f"{settings.ebay_client_id}:{settings.ebay_client_secret}".encode()
        ).decode()
        async with build_client() as client:
            _, payload = await request_json(
                client,
                "POST",
                TOKEN_URL[settings.ebay_env],
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data="grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope",
            )
        self._token = payload["access_token"]
        return {"Authorization": f"Bearer {self._token}"}

    async def search(self, query: str, *, limit: int = 20) -> list[NormalizedListing]:
        if self._missing_credentials():
            return []
        headers = await self._token_header()
        marketplace = settings.ebay_marketplace_list()[0]
        headers["X-EBAY-C-MARKETPLACE-ID"] = marketplace
        async with build_client() as client:
            _, payload = await request_json(
                client,
                "GET",
                SEARCH_URL[settings.ebay_env],
                headers=headers,
                params={"q": query, "limit": str(min(limit, 50))},
            )
        return [self._normalize(item) for item in payload.get("itemSummaries") or []]

    def _normalize(self, item: dict[str, Any]) -> NormalizedListing:
        price = item.get("price") or {}
        ship = (item.get("shippingOptions") or [{}])[0]
        ship_cost = (ship.get("shippingCost") or {}).get("value")
        loc = item.get("itemLocation") or {}
        country = str(loc.get("country") or "UN")[:2]
        images = [img.get("imageUrl") for img in (item.get("thumbnailImages") or []) if img.get("imageUrl")]
        return NormalizedListing(
            source_id=self.source_id,
            external_id=str(item.get("itemId") or item.get("legacyItemId")),
            url=str(item.get("itemWebUrl") or ""),
            title=str(item.get("title") or ""),
            seller=(item.get("seller") or {}).get("username"),
            seller_type="marketplace",
            seller_location=loc.get("city"),
            country=country,
            currency=str(price.get("currency") or "EUR"),
            asking_price=Decimal(str(price["value"])) if price.get("value") else None,
            shipping_cost=Decimal(str(ship_cost)) if ship_cost else None,
            condition_raw=item.get("condition"),
            category=(item.get("categories") or [{}])[0].get("categoryName"),
            images=images,
            extras={
                "buyingOptions": item.get("buyingOptions"),
                "note": "Active listings are asking prices, not realised sales.",
            },
            raw=item,
            source_confidence=Decimal("0.90"),
        )
