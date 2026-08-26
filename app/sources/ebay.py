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
from app.privacy.ebay_minimise import minimise_normalized_listing
from app.sources.base import HealthProof, NormalizedListing, SourceAdapter
from app.sources.ebay_filters import (
    browse_filter,
    category_id_for_query,
    marketplace_currency,
    price_band_for_query,
    reject_listing_fields,
)

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


def api_root(env: str) -> str:
    return "https://api.ebay.com" if env == "production" else "https://api.sandbox.ebay.com"


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
            "env": settings.ebay_api_env,
            "configured_ebay_env": settings.ebay_env,
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
        host_token = TOKEN_URL[settings.ebay_api_env]
        host_search = SEARCH_URL[settings.ebay_api_env]
        sandbox_used = "sandbox" in host_token or "sandbox" in host_search
        base_proof = {
            **self.credential_status(),
            "token_host": host_token,
            "search_host": host_search,
            "sandbox_used": sandbox_used,
            "api_root": api_root(settings.ebay_api_env),
            "fail_closed": True,
            "silent_sandbox_fallback": False,
        }
        if self._missing_credentials():
            return HealthProof(
                status=SourceStatus.BLOCKED_CREDENTIALS,
                ok=False,
                http_status=None,
                latency_ms=None,
                records=0,
                detail="EBAY_CLIENT_ID / EBAY_CLIENT_SECRET not configured. Create an app at developer.ebay.com.",
                proof=base_proof,
            )
        started = time.perf_counter()
        oauth = await self._oauth_probe()
        base_proof["oauth"] = oauth
        if not oauth.get("ok"):
            status = SourceStatus.BLOCKED_CREDENTIALS
            error = str(oauth.get("error") or "")
            if (
                settings.ebay_api_env == "production"
                and oauth.get("http_status") == 401
                and "invalid_client" in error
            ):
                status = SourceStatus.PRODUCTION_KEYSET_DISABLED_COMPLIANCE
            return HealthProof(
                status=status,
                ok=False,
                http_status=oauth.get("http_status"),
                latency_ms=int((time.perf_counter() - started) * 1000),
                records=0,
                detail=(
                    "Production keyset appears disabled pending Marketplace Account Deletion "
                    "compliance (invalid_client). Do not regenerate keys. Complete the notification "
                    "endpoint in the eBay Developer portal."
                    if status is SourceStatus.PRODUCTION_KEYSET_DISABLED_COMPLIANCE
                    else str(oauth.get("error") or "OAuth failed")
                ),
                proof=base_proof,
            )
        try:
            listings = await self.search("sony a7 iv", limit=3)
            from app.sold.insights import EbayMarketplaceInsightsProvider

            insights = await EbayMarketplaceInsightsProvider(self._token).probe()
            return HealthProof(
                status=SourceStatus.LIVE if listings else SourceStatus.DEGRADED,
                ok=True,
                http_status=200,
                latency_ms=int((time.perf_counter() - started) * 1000),
                records=len(listings),
                detail="Browse search succeeded across configured marketplaces.",
                proof={
                    **base_proof,
                    "sample": listings[0].external_id if listings else None,
                    "sample_url": listings[0].url if listings else None,
                    "sample_item_ids": [item.external_id for item in listings[:3]],
                    "sample_urls": [item.url for item in listings[:3]],
                    "currencies": sorted({item.currency for item in listings}),
                    "countries": sorted({item.country for item in listings if item.country}),
                    "marketplace_insights": insights,
                },
            )
        except Exception as exc:
            logger.warning("ebay_health_failed", error=str(exc))
            status = SourceStatus.BLOCKED_TECHNICAL
            code = getattr(exc, "status_code", None)
            if code in {401, 403}:
                status = SourceStatus.BLOCKED_CREDENTIALS
                if settings.ebay_api_env == "production" and code == 401:
                    status = SourceStatus.PRODUCTION_KEYSET_DISABLED_COMPLIANCE
            return HealthProof(
                status=status,
                ok=False,
                http_status=code,
                latency_ms=int((time.perf_counter() - started) * 1000),
                records=0,
                detail=str(exc),
                proof=base_proof,
            )

    async def _oauth_probe(self) -> dict[str, Any]:
        """Client-credentials grant against the environment-selected host only."""
        import httpx

        url = TOKEN_URL[settings.ebay_api_env]
        basic = base64.b64encode(
            f"{settings.ebay_client_id}:{settings.ebay_client_secret}".encode()
        ).decode()
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Basic {basic}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    data={"grant_type": "client_credentials", "scope": SCOPE},
                )
        except httpx.HTTPError as exc:
            return {"ok": False, "http_status": None, "host": url, "error": type(exc).__name__}
        body = response.text[:220]
        if "access_token" in body:
            body = '{"access_token":"[REDACTED]"}'
        if response.status_code == 200:
            payload = response.json()
            self._token = payload["access_token"]
            self._token_expires = time.time() + int(payload.get("expires_in") or 7200)
            return {
                "ok": True,
                "http_status": 200,
                "host": url,
                "token_type": payload.get("token_type"),
                "expires_in": payload.get("expires_in"),
            }
        return {
            "ok": False,
            "http_status": response.status_code,
            "host": url,
            "error": body,
            "diagnosis": self._diagnose_oauth(response.status_code, body),
        }

    def _diagnose_oauth(self, status: int, body: str) -> list[str]:
        hints = [
            f"EBAY_ENV={settings.ebay_env} effective={settings.ebay_api_env}",
            "OAuth host is production" if settings.ebay_api_env == "production" else "OAuth host is sandbox",
            "Grant = client_credentials, scope = public Browse scope",
            "No silent sandbox fallback",
        ]
        if status == 401 and "invalid_client" in body:
            if settings.ebay_api_env == "production":
                hints.append(
                    "Production invalid_client is the documented result when the keyset is "
                    "disabled pending Marketplace Account Deletion/Closure compliance. "
                    "Do not regenerate keys. Expose GET/POST /webhooks/ebay/account-deletion "
                    "over HTTPS, enter the endpoint + verification token in the Developer "
                    "portal, then re-run make ebay-check after the dashboard shows the "
                    "Production keyset enabled."
                )
            else:
                hints.append(
                    "eBay rejected the client id/secret pair (invalid_client). "
                    "Re-copy App ID + Cert ID from developer.ebay.com."
                )
        if status == 403:
            hints.append("Token endpoint 403: keyset may lack OAuth entitlement.")
        return hints

    async def _token_header(self) -> dict[str, str]:
        if self._token and time.time() < self._token_expires - 60:
            return {"Authorization": f"Bearer {self._token}"}
        oauth = await self._oauth_probe()
        if not oauth.get("ok") or not self._token:
            raise SourceHttpError(int(oauth.get("http_status") or 401), TOKEN_URL[settings.ebay_api_env], str(oauth.get("error") or "oauth"))
        return {"Authorization": f"Bearer {self._token}"}

    async def marketplace_sweep(self, *, queries: list[str] | None = None, per_market: int = 6) -> list[dict[str, Any]]:
        queries = queries or [
            "Sony FE 24-70mm GM II",
            "Sony A7 IV",
            "Canon RF 24-70 f/2.8",
            "MacBook Pro M3",
            "iPhone 15 Pro 256GB",
            "RTX 4070",
            "PlayStation 5",
            "Pioneer DDJ-1000",
            "Shure SM7B",
        ]
        rows: list[dict[str, Any]] = []
        for marketplace in settings.ebay_marketplace_list():
            for query in queries:
                try:
                    listings = await self.search(query, limit=per_market, marketplaces=[marketplace])
                except Exception as exc:
                    rows.append({"marketplace": marketplace, "query": query, "ok": False, "error": type(exc).__name__})
                    continue
                rows.append({
                    "marketplace": marketplace,
                    "query": query,
                    "ok": True,
                    "count": len(listings),
                    "currencies": sorted({item.currency for item in listings}),
                    "countries": sorted({item.country for item in listings if item.country}),
                    "conditions": sorted({item.condition_raw or "" for item in listings if item.condition_raw}),
                    "sample_ids": [item.external_id for item in listings[:2]],
                    "sample_urls": [item.url for item in listings[:2]],
                    "search_host": SEARCH_URL[settings.ebay_api_env],
                })
        return rows

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
        if settings.ebay_api_env == "sandbox" and "EBAY_US" not in markets:
            # Sandbox catalogue is mostly US dummy inventory; keep owner markets first.
            markets = list(markets) + ["EBAY_US"]
        out: list[NormalizedListing] = []
        remaining = min(limit, 80)
        # Fetch a usable page per marketplace instead of splitting 2-wide across seven sites.
        per_market = max(6, remaining // max(1, len(markets)))
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
        min_price, max_price = price_band_for_query(query)
        currency = marketplace_currency(marketplace)
        category_id = category_id_for_query(query)
        include_parts = "parts" in (query or "").lower()
        while len(items) < limit:
            params: dict[str, str] = {
                "q": query,
                "limit": str(page),
                "offset": str(offset),
                "filter": browse_filter(
                    min_price=min_price,
                    max_price=max_price,
                    currency=currency,
                    include_parts=include_parts,
                ),
            }
            if category_id:
                params["category_ids"] = category_id
            async with build_client() as client:
                try:
                    _, payload = await request_json(
                        client,
                        "GET",
                        SEARCH_URL[settings.ebay_api_env],
                        headers=headers,
                        params=params,
                    )
                except SourceHttpError as exc:
                    if exc.status_code == 429:
                        logger.warning("ebay_429", market=marketplace)
                    raise
            batch = payload.get("itemSummaries") or []
            if not batch:
                break
            for raw in batch:
                listing = self._normalize(raw, marketplace)
                leaf_cat = None
                cats = raw.get("categories") or []
                if cats:
                    leaf_cat = str(cats[0].get("categoryId") or "") or None
                reason = reject_listing_fields(
                    query,
                    title=listing.title,
                    currency=listing.currency,
                    marketplace=marketplace,
                    asking_price=listing.asking_price,
                    min_price=min_price,
                    max_price=max_price,
                    category_id=leaf_cat,
                    condition_id=str(raw.get("conditionId") or "") or None,
                )
                if reason:
                    listing.extras["rejected_reason"] = reason
                    continue
                items.append(listing)
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
                ITEM_URL[settings.ebay_api_env] + external_id,
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
        listing = NormalizedListing(
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
                "conditionId": item.get("conditionId"),
                "conditionDescription": item.get("conditionDescription"),
                "categoryId": (item.get("categories") or [{}])[0].get("categoryId"),
                "full_item": full,
                "sandbox": settings.ebay_api_env == "sandbox",
                "note": (
                    "SANDBOX dummy listing. Not a real-money acquisition."
                    if settings.ebay_api_env == "sandbox"
                    else "Active listings are asking prices, not realised sales."
                ),
            },
            raw=item,
            source_confidence=Decimal("0.90"),
            observed_at=datetime.now(timezone.utc),
        )
        return minimise_normalized_listing(listing)
