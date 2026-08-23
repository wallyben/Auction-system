"""eBay Browse API — first-class production source when official credentials exist."""

from __future__ import annotations

import base64
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.core.config import settings
from app.core.http import SourceHttpError, build_client, request_json
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
ITEM_URL = {
    "production": "https://api.ebay.com/buy/browse/v1/item/",
    "sandbox": "https://api.sandbox.ebay.com/buy/browse/v1/item/",
}

SCOPE = "https://api.ebay.com/oauth/api_scope"


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
        self._token_expires: float = 0

    def _missing_credentials(self) -> bool:
        return not settings.ebay_client_id or not settings.ebay_client_secret

    def credential_status(self) -> dict[str, object]:
        return {
            "configured": not self._missing_credentials(),
            "env": settings.ebay_env,
            "marketplaces": settings.ebay_marketplace_list(),
            "docs": "https://developer.ebay.com/api-docs/static/oauth-client-credentials-grant.html",
            "setup": [
                "Create an app at https://developer.ebay.com/my/keys",
                "Enable the Buy Browse API",
                "Set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET in .env",
                "Optionally set EBAY_ENV=sandbox and EBAY_MARKETPLACES",
                "Run: make ebay-check",
            ],
        }

    async def healthcheck(self) -> HealthProof:
        if self._missing_credentials():
            return HealthProof(
                status=SourceStatus.BLOCKED_CREDENTIALS,
                ok=False,
                http_status=None,
                latency_ms=None,
                records=0,
                detail="EBAY_CLIENT_ID / EBAY_CLIENT_SECRET not configured. Create an app at developer.ebay.com.",
                proof=self.credential_status(),
            )
        started = time.perf_counter()
        try:
            listings = await self.search("sony a7", limit=2, marketplaces=settings.ebay_marketplace_list()[:2])
            return HealthProof(
                status=SourceStatus.LIVE if listings else SourceStatus.DEGRADED,
                ok=bool(listings),
                http_status=200,
                latency_ms=int((time.perf_counter() - started) * 1000),
                records=len(listings),
                detail="Browse search succeeded across configured marketplaces.",
                proof={"sample": listings[0].external_id if listings else None, **self.credential_status()},
            )
        except Exception as exc:
            logger.warning("ebay_health_failed", error=str(exc))
            status = SourceStatus.BLOCKED_TECHNICAL
            code = getattr(exc, "status_code", None)
            if code in {401, 403}:
                status = SourceStatus.BLOCKED_CREDENTIALS
            return HealthProof(
                status=status,
                ok=False,
                http_status=code,
                latency_ms=int((time.perf_counter() - started) * 1000),
                records=0,
                detail=str(exc),
                proof=self.credential_status(),
            )

    async def _token_header(self) -> dict[str, str]:
        if self._token and time.time() < self._token_expires - 60:
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
                data=f"grant_type=client_credentials&scope={SCOPE}",
            )
        self._token = payload["access_token"]
        self._token_expires = time.time() + int(payload.get("expires_in") or 7200)
        return {"Authorization": f"Bearer {self._token}"}

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        marketplaces: list[str] | None = None,
    ) -> list[NormalizedListing]:
        if self._missing_credentials():
            return []
        markets = marketplaces or settings.ebay_marketplace_list()
        out: list[NormalizedListing] = []
        remaining = min(limit, 80)
        per_market = max(1, remaining // max(1, len(markets)))
        for market in markets:
            if remaining <= 0:
                break
            got = await self._search_market(query, market, min(per_market, remaining))
            out.extend(got)
            remaining -= len(got)
        return out[:limit]

    async def _search_market(self, query: str, marketplace: str, limit: int) -> list[NormalizedListing]:
        headers = await self._token_header()
        headers["X-EBAY-C-MARKETPLACE-ID"] = marketplace
        items: list[NormalizedListing] = []
        offset = 0
        page = min(limit, 50)
        while len(items) < limit:
            async with build_client() as client:
                try:
                    _, payload = await request_json(
                        client,
                        "GET",
                        SEARCH_URL[settings.ebay_env],
                        headers=headers,
                        params={"q": query, "limit": str(page), "offset": str(offset)},
                    )
                except SourceHttpError as exc:
                    if exc.status_code == 429:
                        logger.warning("ebay_429", market=marketplace)
                    raise
            batch = payload.get("itemSummaries") or []
            if not batch:
                break
            items.extend(self._normalize(item, marketplace) for item in batch)
            offset += len(batch)
            if len(batch) < page:
                break
        return items[:limit]

    async def fetch_listing(self, external_id: str) -> NormalizedListing | None:
        if self._missing_credentials():
            return None
        headers = await self._token_header()
        headers["X-EBAY-C-MARKETPLACE-ID"] = settings.ebay_marketplace_list()[0]
        async with build_client() as client:
            _, payload = await request_json(
                client,
                "GET",
                ITEM_URL[settings.ebay_env] + external_id,
                headers=headers,
            )
        return self._normalize(payload, settings.ebay_marketplace_list()[0], full=True)

    def _normalize(self, item: dict[str, Any], marketplace: str, *, full: bool = False) -> NormalizedListing:
        price = item.get("price") or item.get("currentBidPrice") or {}
        current_bid = item.get("currentBidPrice") or {}
        bin_price = item.get("price") if "AUCTION" in (item.get("buyingOptions") or []) else None
        ship = (item.get("shippingOptions") or [{}])[0]
        ship_cost = (ship.get("shippingCost") or {}).get("value")
        loc = item.get("itemLocation") or {}
        country = str(loc.get("country") or marketplace.replace("EBAY_", "")[:2] or "UN")[:2]
        images = [img.get("imageUrl") for img in (item.get("thumbnailImages") or []) if img.get("imageUrl")]
        if item.get("image", {}).get("imageUrl"):
            images.insert(0, item["image"]["imageUrl"])
        specifics = {}
        for aspect in item.get("localizedAspects") or []:
            name = str(aspect.get("name") or "")
            value = aspect.get("value")
            if name and value:
                specifics[name.lower()] = value if isinstance(value, str) else str(value)
        ids = item.get("additionalProductIdentities") or []
        gtin = mpn = None
        for block in ids:
            for ident in block.get("productIdentity") or []:
                typ = str(ident.get("identifierType") or "").upper()
                val = ident.get("identifierValue")
                if typ in {"EAN", "UPC", "ISBN", "GTIN"} and val:
                    gtin = str(val)
                if typ in {"MPN", "BRAND_MPN"} and val:
                    mpn = str(val)
        buying = item.get("buyingOptions") or []
        listing_type = "auction" if "AUCTION" in buying and "FIXED_PRICE" not in buying else "fixed"
        ends = item.get("itemEndDate")
        ends_at = None
        if ends:
            try:
                ends_at = datetime.fromisoformat(str(ends).replace("Z", "+00:00"))
            except ValueError:
                ends_at = None
        seller = item.get("seller") or {}
        return NormalizedListing(
            source_id=self.source_id,
            external_id=str(item.get("itemId") or item.get("legacyItemId")),
            url=str(item.get("itemWebUrl") or ""),
            title=str(item.get("title") or ""),
            description=str(item.get("shortDescription") or item.get("description") or "")[:4000],
            seller=seller.get("username"),
            seller_type="marketplace",
            seller_location=loc.get("city"),
            country=country,
            currency=str(price.get("currency") or current_bid.get("currency") or "EUR"),
            asking_price=Decimal(str(price["value"])) if price.get("value") else None,
            current_bid=Decimal(str(current_bid["value"])) if current_bid.get("value") else None,
            buy_now_price=Decimal(str(bin_price["value"])) if isinstance(bin_price, dict) and bin_price.get("value") else None,
            shipping_cost=Decimal(str(ship_cost)) if ship_cost else None,
            condition_raw=item.get("condition"),
            category=(item.get("categories") or [{}])[0].get("categoryName"),
            brand=specifics.get("brand"),
            model=specifics.get("model") or specifics.get("mpn"),
            gtin=gtin,
            mpn=mpn or specifics.get("mpn"),
            listing_type=listing_type,
            ends_at=ends_at,
            images=images,
            extras={
                "marketplace": marketplace,
                "buyingOptions": buying,
                "seller_feedback": seller.get("feedbackPercentage"),
                "seller_score": seller.get("feedbackScore"),
                "epid": item.get("epid"),
                "legacyItemId": item.get("legacyItemId"),
                "itemSpecifics": specifics,
                "full_item": full,
                "note": "Active listings are asking prices, not realised sales.",
            },
            raw=item,
            source_confidence=Decimal("0.90"),
            observed_at=datetime.now(timezone.utc),
        )
