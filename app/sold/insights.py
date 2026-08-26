"""eBay Marketplace Insights — Limited Release sold-item API.

Official surface (do not brute-force alternatives):
  GET https://api.ebay.com/buy/marketplace_insights/v1_beta/item_sales/search

Required: category_ids. Ordinary Buy apps receive HTTP 403 (not entitled).
v1 (non-beta) is not a documented public replacement; 404 is expected. Do not probe it.

Owner action if access is required:
  Apply via eBay Buy APIs Requirements.
  https://developer.ebay.com/develop/guides-v2/buy-apis-requirements
Until HTTP 200, this provider returns no sold evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import settings
from app.models.enums import EvidenceType
from app.sold.provider import SoldEvidenceHit

INSIGHTS_URL = {
    "production": "https://api.ebay.com/buy/marketplace_insights/v1_beta/item_sales/search",
    "sandbox": "https://api.sandbox.ebay.com/buy/marketplace_insights/v1_beta/item_sales/search",
}

# Digital Cameras — Insights requires category_ids on search.
PROBE_CATEGORY_ID = "31388"

BUY_API_REQUIREMENTS = "https://developer.ebay.com/develop/guides-v2/buy-apis-requirements"
INSIGHTS_DOCS = "https://developer.ebay.com/api-docs/buy/marketplace-insights/resources/item_sales/methods/search"


class EbayMarketplaceInsightsProvider:
    name = "ebay_marketplace_insights"
    classification = "REALIZED_SOLD"
    _entitled: bool = False
    _last_probe: dict[str, Any] | None = None

    def __init__(self, token: str | None = None) -> None:
        self.token = token

    async def search_realised_sales(
        self, product: str, market: str, condition: str, *, limit: int = 20
    ) -> list[SoldEvidenceHit]:
        if not self._entitled or not (self.token or ""):
            return []
        env = settings.ebay_api_env
        from app.sources.ebay_filters import category_id_for_query

        category_id = category_id_for_query(product) or PROBE_CATEGORY_ID
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                INSIGHTS_URL[env],
                params={
                    "q": product[:80],
                    "limit": str(min(limit, 20)),
                    "category_ids": category_id,
                },
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "X-EBAY-C-MARKETPLACE-ID": market if str(market).startswith("EBAY_") else "EBAY_IE",
                },
            )
        if response.status_code != 200:
            self._entitled = False
            return []
        hits: list[SoldEvidenceHit] = []
        for item in (response.json() or {}).get("itemSales") or []:
            if not isinstance(item, dict):
                continue
            price = item.get("lastSoldPrice") or {}
            try:
                amount = Decimal(str(price.get("value")))
            except Exception:
                continue
            sold_raw = item.get("lastSoldDate")
            try:
                sold_at = datetime.fromisoformat(str(sold_raw).replace("Z", "+00:00")) if sold_raw else datetime.now(timezone.utc)
            except ValueError:
                sold_at = datetime.now(timezone.utc)
            title = str(item.get("title") or product)
            hits.append(
                SoldEvidenceHit(
                    source=self.name,
                    title=title,
                    sold_price_eur=amount,
                    territory=(item.get("itemLocation") or {}).get("country") or "UN",
                    condition=str(item.get("condition") or condition or "unknown"),
                    channel="ebay_insights",
                    sold_date=sold_at,
                    evidence_type=EvidenceType.REALISED_SALE,
                    quality="high",
                    url=item.get("itemWebUrl"),
                    notes="Marketplace Insights completed sale. Official first-party sold evidence.",
                    variant="",
                    currency=str(price.get("currency") or "EUR"),
                    identity_key=title[:180],
                    provenance="ebay_marketplace_insights_v1_beta",
                    market=market,
                )
            )
            if len(hits) >= limit:
                break
        return hits

    async def healthcheck(self) -> dict[str, object]:
        return await self.probe()

    async def freshness(self) -> datetime | None:
        return None

    async def probe(self, token: str | None = None) -> dict[str, Any]:
        env = settings.ebay_api_env
        url = INSIGHTS_URL[env]
        bearer = token or self.token
        if not bearer:
            return {
                "provider": self.name,
                "available": False,
                "http_status": None,
                "classification": "UNAVAILABLE",
                "entitled": False,
                "official_endpoint": url,
                "owner_action": (
                    "Marketplace Insights is Limited Release. Apply via Buy APIs Requirements: "
                    f"{BUY_API_REQUIREMENTS}. Do not brute-force other hosts."
                ),
                "docs": INSIGHTS_DOCS,
                "note": "No access token. Insights not probed.",
            }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(
                    url,
                    params={"q": "sony a7 iv", "limit": "1", "category_ids": PROBE_CATEGORY_ID},
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
                "classification": "UNAVAILABLE",
                "entitled": False,
                "owner_action": f"Retry later or apply at {BUY_API_REQUIREMENTS}.",
            }
            self._last_probe = last
            return last
        body_excerpt = response.text[:180].replace("\n", " ")
        if "access_token" in body_excerpt:
            body_excerpt = "[redacted]"
        entitled = response.status_code == 200
        self._entitled = entitled
        note = {
            200: "Entitled. Completed sales may be used as REALIZED_SOLD evidence.",
            403: (
                "Not entitled (Limited Release). This app cannot read Marketplace Insights. "
                f"Owner action: apply at {BUY_API_REQUIREMENTS}. Stop relying on Insights until 200."
            ),
            400: "Request rejected. Probe uses official v1_beta + required category_ids.",
            401: "Token rejected. Client-credentials Browse tokens usually lack Insights scope.",
        }.get(
            response.status_code,
            "Non-200. Treated as unavailable. v1 (non-beta) is not probed.",
        )
        last = {
            "provider": self.name,
            "available": entitled,
            "http_status": response.status_code,
            "url_probed": url,
            "classification": self.classification if entitled else "UNAVAILABLE",
            "entitled": entitled,
            "body_excerpt": body_excerpt,
            "required_param": "category_ids",
            "docs": INSIGHTS_DOCS,
            "owner_action": None if entitled else f"Apply for Limited Release access: {BUY_API_REQUIREMENTS}",
            "note": note,
        }
        self._last_probe = last
        return last
