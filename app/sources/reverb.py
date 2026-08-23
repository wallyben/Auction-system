"""Reverb public listings adapter. Official JSON API; public search does not require a token."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from app.core.http import SourceHttpError, build_client, request_json
from app.core.logging import get_logger
from app.models.enums import SourceKind, SourceStatus
from app.sources.base import HealthProof, NormalizedListing, SourceAdapter

logger = get_logger("arie.sources.reverb")
REVERB_LISTINGS = "https://reverb.com/api/listings"


def _money(blob: dict[str, Any] | None) -> Decimal | None:
    if not blob or blob.get("amount") is None:
        return None
    return Decimal(str(blob["amount"]))


def _shipping(shipping: dict[str, Any] | None) -> Decimal | None:
    if not shipping:
        return None
    preferred: Decimal | None = None
    for rate in shipping.get("rates") or []:
        region = str(rate.get("region_code") or "")
        amount = _money(rate.get("rate") or {})
        if amount is None:
            continue
        if region in {"IE", "EU"}:
            return amount
        if region in {"XX", "GB_NIR"}:
            preferred = amount
    rates = shipping.get("rates") or []
    if preferred is not None:
        return preferred
    return _money((rates[0].get("rate") or {}) if rates else None)


class ReverbAdapter(SourceAdapter):
    source_id = "reverb"
    display_name = "Reverb"
    country = "US"
    kind = SourceKind.ACQUISITION
    official_api = True
    access_method = "official_public_json"
    credentials_required = False
    cadence_minutes = 15

    async def healthcheck(self) -> HealthProof:
        started = time.perf_counter()
        try:
            async with build_client() as client:
                response, payload = await request_json(
                    client,
                    "GET",
                    REVERB_LISTINGS,
                    headers={"Accept": "application/hal+json", "Accept-Version": "3.0"},
                    params={"query": "fender", "per_page": 1},
                )
            listings = payload.get("listings") or []
            sample = listings[0] if listings else {}
            return HealthProof(
                status=SourceStatus.LIVE if listings else SourceStatus.DEGRADED,
                ok=bool(listings),
                http_status=response.status_code,
                latency_ms=int((time.perf_counter() - started) * 1000),
                records=len(listings),
                detail="Public listings endpoint returned inventory." if listings else "Empty listings payload.",
                proof={
                    "url": REVERB_LISTINGS,
                    "sample_id": sample.get("id"),
                    "sample_title": sample.get("title"),
                    "sample_url": ((sample.get("_links") or {}).get("web") or {}).get("href"),
                    "total": payload.get("total"),
                },
            )
        except Exception as exc:
            logger.warning("reverb_health_failed", error=str(exc))
            return HealthProof(
                status=SourceStatus.BLOCKED_TECHNICAL,
                ok=False,
                http_status=getattr(exc, "status_code", None),
                latency_ms=int((time.perf_counter() - started) * 1000),
                records=0,
                detail=str(exc),
                proof={},
            )

    async def search(self, query: str, *, limit: int = 20) -> list[NormalizedListing]:
        async with build_client() as client:
            _, payload = await request_json(
                client,
                "GET",
                REVERB_LISTINGS,
                headers={
                    "Accept": "application/hal+json",
                    "Accept-Version": "3.0",
                    "X-Display-Currency": "EUR",
                },
                params={"query": query, "per_page": min(limit, 50)},
            )
        return [self._normalize(item) for item in payload.get("listings") or []]

    async def fetch_listing(self, external_id: str) -> NormalizedListing | None:
        try:
            async with build_client() as client:
                _, payload = await request_json(
                    client,
                    "GET",
                    f"{REVERB_LISTINGS}/{external_id}",
                    headers={"Accept": "application/hal+json", "Accept-Version": "3.0"},
                )
        except SourceHttpError:
            return None
        return self._normalize(payload)

    def _normalize(self, item: dict[str, Any]) -> NormalizedListing:
        links = item.get("_links") or {}
        web = (links.get("web") or {}).get("href") or f"https://reverb.com/item/{item.get('id')}"
        images: list[str] = []
        photo = (links.get("photo") or {}).get("href")
        if photo:
            images.append(photo)
        condition = item.get("condition") or {}
        price = item.get("price") or {}
        shop = item.get("shop") or {}
        loc = shop.get("address") if isinstance(shop, dict) else None
        country = "US"
        if isinstance(loc, dict) and loc.get("country_code"):
            country = str(loc["country_code"])[:2].upper()
        return NormalizedListing(
            source_id=self.source_id,
            external_id=str(item.get("id")),
            url=web,
            title=str(item.get("title") or ""),
            description=str(item.get("description") or ""),
            seller=item.get("shop_name"),
            seller_type="dealer",
            seller_location=None,
            country=country,
            currency=str(price.get("currency") or item.get("listing_currency") or "USD"),
            asking_price=_money(price),
            shipping_cost=_shipping(item.get("shipping")),
            shipping_currency=str(price.get("currency") or "EUR"),
            condition_raw=condition.get("display_name") if isinstance(condition, dict) else None,
            category="music_dj",
            brand=item.get("make"),
            model=item.get("model"),
            listing_type="auction" if item.get("auction") else "fixed",
            images=images,
            extras={"shop_id": item.get("shop_id"), "state": item.get("state")},
            raw=item,
            source_confidence=Decimal("0.85"),
        )
