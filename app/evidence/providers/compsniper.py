"""CompSniper sold-listings API adapter.

One request = one product/marketplace keyword search, not one active listing.
Health checks never debit quota.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import SourceStatus

logger = get_logger("arie.compsniper")

BASE_URL = "https://api.compsniper.com"
SCRAPE_PATH = "/v1/scrape"
VALID_SITES = {
    "ebay.com",
    "ebay.co.uk",
    "ebay.de",
    "ebay.fr",
    "ebay.it",
    "ebay.es",
    "ebay.ca",
    "ebay.com.au",
}

LIVE = SourceStatus.LIVE.value
BLOCKED_CREDENTIALS = SourceStatus.BLOCKED_CREDENTIALS.value
DEGRADED = SourceStatus.DEGRADED.value
DISABLED = SourceStatus.DISABLED.value


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class CompSniperHealth:
    provider: str = "compsniper"
    status: str = DISABLED
    configured: bool = False
    reachable: bool | None = None
    last_http_status: int | None = None
    quota_remaining: int | None = None
    quota_limit: int | None = None
    rate_limit_remaining: int | None = None
    rate_limit_limit: int | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    requests_today: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    last_error_code: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "status": self.status,
            "configured": self.configured,
            "enabled": bool(_key()),
            "reachable": self.reachable,
            "last_http_status": self.last_http_status,
            "quota_remaining": self.quota_remaining,
            "quota_limit": self.quota_limit,
            "rate_limit_remaining": self.rate_limit_remaining,
            "rate_limit_limit": self.rate_limit_limit,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "last_error": self.last_error,
            "last_error_code": self.last_error_code,
            "requests_today": self.requests_today,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_pct": round(
                100.0 * self.cache_hits / (self.cache_hits + self.cache_misses), 1
            )
            if (self.cache_hits + self.cache_misses)
            else None,
        }


HEALTH = CompSniperHealth()


def reset_health_for_tests() -> None:
    HEALTH.status = DISABLED
    HEALTH.configured = False
    HEALTH.reachable = None
    HEALTH.last_http_status = None
    HEALTH.quota_remaining = None
    HEALTH.quota_limit = None
    HEALTH.rate_limit_remaining = None
    HEALTH.rate_limit_limit = None
    HEALTH.last_success_at = None
    HEALTH.last_error = None
    HEALTH.requests_today = 0
    HEALTH.cache_hits = 0
    HEALTH.cache_misses = 0
    HEALTH.last_error_code = None


def _key() -> str:
    return (settings.compsniper_api_key or "").strip()


COMPLETED_LISTING_TYPES = {
    "sold",
    "buy_it_now",
    "buyitnow",
    "auction",
    "best_offer_accepted",
    "bestofferaccepted",
    "offer",
    "",
}


def _enabled() -> bool:
    """A configured API key enables CompSniper.

    COMPSNIPER_ENABLED defaulted false, so production could hold a live key
    and still never query. The key is the credential; blank key disables.
    """
    return bool(_key())


def provider_status() -> str:
    if HEALTH.last_error_code == "unauthorized" or HEALTH.last_http_status == 401:
        return BLOCKED_CREDENTIALS
    if HEALTH.last_error_code in {"quota_exceeded", "rate_limited"} or HEALTH.last_http_status in {429, 502, 503}:
        return DEGRADED
    if HEALTH.last_http_status and HEALTH.last_http_status >= 500:
        return DEGRADED
    if HEALTH.last_success_at or HEALTH.last_http_status == 200:
        return LIVE
    if not _key():
        return BLOCKED_CREDENTIALS
    return LIVE


def compsniper_health() -> dict[str, object]:
    HEALTH.configured = bool(_key()) or bool(HEALTH.last_http_status)
    HEALTH.status = provider_status()
    if HEALTH.status == DISABLED and not HEALTH.last_error:
        HEALTH.last_error = "COMPSNIPER_API_KEY is not set." if not _key() else "CompSniper disabled."
    if HEALTH.status == BLOCKED_CREDENTIALS and not HEALTH.last_error:
        HEALTH.last_error = "COMPSNIPER_API_KEY is not set."
    return HEALTH.as_dict()


def _apply_headers(headers: httpx.Headers, status_code: int) -> None:
    def _int(*names: str) -> int | None:
        for name in names:
            raw = headers.get(name)
            if raw is None:
                continue
            try:
                return int(str(raw).split(";")[0].strip())
            except ValueError:
                continue
        return None

    HEALTH.rate_limit_limit = _int("X-RateLimit-Limit", "RateLimit-Limit", "X-Rate-Limit-Limit")
    HEALTH.rate_limit_remaining = _int(
        "X-RateLimit-Remaining", "RateLimit-Remaining", "X-Rate-Limit-Remaining"
    )
    HEALTH.quota_limit = _int("X-Usage-Limit", "X-Quota-Limit", "X-Monthly-Limit")
    remaining = _int("X-Usage-Remaining", "X-Quota-Remaining", "X-Monthly-Remaining")
    if remaining is not None:
        HEALTH.quota_remaining = remaining
    HEALTH.last_http_status = status_code


def parse_money(value: object) -> Decimal | None:
    if value in (None, "", "null"):
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except Exception:
        return None


def parse_sold_at(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if "T" in text:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        dt = datetime.strptime(text[:10], "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class CompSniperItem:
    item_id: str
    url: str | None
    epid: str | None
    title: str
    condition: str | None
    condition_id: int | None
    buying_format: str | None
    best_offer_accepted: bool
    listing_type: str
    ended_at: datetime | None
    sold_price: Decimal | None
    sold_currency: str | None
    shipping_price: Decimal | None
    shipping_currency: str | None
    shipping_type: str | None
    total_price: Decimal | None
    seller_username: str | None
    seller_positive_percent: float | None
    seller_feedback_score: int | None
    item_location: str | None
    scraped_at: datetime | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CompSniperPage:
    keyword: str
    page: int
    total_items: int
    has_next_page: bool
    items: list[CompSniperItem]
    raw: dict[str, Any]
    ok: bool
    http_status: int
    error_code: str | None = None
    error: str | None = None


def _first(payload: dict[str, Any], *keys: str) -> object:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _money_and_currency(value: object, currency_fallback: object) -> tuple[Decimal | None, str | None]:
    if isinstance(value, dict):
        amount = parse_money(value.get("amount") or value.get("value") or value.get("price"))
        currency = str(value.get("currency") or value.get("currencyCode") or currency_fallback or "") or None
        return amount, currency
    return parse_money(value), (str(currency_fallback or "") or None)


def parse_item(payload: dict[str, Any]) -> CompSniperItem | None:
    if not isinstance(payload, dict):
        return None
    item_id = str(_first(payload, "itemId", "item_id", "id") or "").strip()
    title = str(_first(payload, "title", "itemTitle", "name") or "").strip()
    listing_type = str(_first(payload, "listingType", "listing_type") or "sold").lower().replace(" ", "_")
    if not item_id and not title:
        return None
    cid = _first(payload, "conditionId", "condition_id")
    try:
        condition_id = int(cid) if cid is not None else None
    except (TypeError, ValueError):
        condition_id = None
    boa = _first(payload, "bestOfferAccepted", "isBestOfferAccepted", "best_offer_accepted")
    if listing_type in {"best_offer_accepted", "bestofferaccepted"}:
        boa = True
    sold_price, sold_currency = _money_and_currency(
        _first(payload, "soldPrice", "sold_price", "price", "salePrice"),
        _first(payload, "soldCurrency", "sold_currency", "currency"),
    )
    shipping_price, shipping_currency = _money_and_currency(
        _first(payload, "shippingPrice", "shipping_price"),
        _first(payload, "shippingCurrency", "shipping_currency", "soldCurrency", "currency"),
    )
    total_price, _ = _money_and_currency(_first(payload, "totalPrice", "total_price"), sold_currency)
    return CompSniperItem(
        item_id=item_id or str(_first(payload, "url") or title)[:64],
        url=str(_first(payload, "url", "itemUrl", "itemWebUrl") or "") or None,
        epid=str(_first(payload, "epid", "ePID") or "") or None,
        title=title,
        condition=str(_first(payload, "condition", "conditionDisplayName") or "") or None,
        condition_id=condition_id,
        buying_format=str(_first(payload, "buyingFormat", "buying_format") or "") or None,
        best_offer_accepted=bool(boa),
        listing_type=listing_type,
        ended_at=parse_sold_at(_first(payload, "endedAt", "ended_at", "soldAt", "sold_date", "endDate")),
        sold_price=sold_price,
        sold_currency=sold_currency,
        shipping_price=shipping_price,
        shipping_currency=shipping_currency,
        shipping_type=str(_first(payload, "shippingType", "shipping_type") or "") or None,
        total_price=total_price,
        seller_username=str(_first(payload, "sellerUsername", "seller_username") or "") or None,
        seller_positive_percent=_optional_float(_first(payload, "sellerPositivePercent", "seller_positive_percent")),
        seller_feedback_score=_optional_int(_first(payload, "sellerFeedbackScore", "seller_feedback_score")),
        item_location=str(_first(payload, "itemLocation", "item_location") or "") or None,
        scraped_at=parse_sold_at(_first(payload, "scrapedAt", "scraped_at")),
        raw=payload,
    )


class CompSniperError(RuntimeError):
    def __init__(self, status_code: int, code: str | None, message: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class CompSniperProvider:
    name = "compsniper"
    source_type = "market_wide_completed_sale"

    def __init__(self, api_key: str | None = None, *, enabled: bool | None = None) -> None:
        self.api_key = (api_key if api_key is not None else _key()).strip()
        self.enabled = _enabled() if enabled is None else enabled

    async def healthcheck(self) -> dict[str, object]:
        """Quota-free status. Never calls /v1/scrape."""
        return compsniper_health()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": settings.http_user_agent,
        }

    async def scrape(
        self,
        keyword: str,
        *,
        ebay_site: str = "ebay.co.uk",
        count: int = 240,
        page: int = 1,
        category_id: str | None = None,
        item_condition: str = "used",
        sold: bool = True,
        client: httpx.AsyncClient | None = None,
    ) -> CompSniperPage:
        if not self.enabled:
            HEALTH.status = DISABLED
            return CompSniperPage(
                keyword=keyword, page=page, total_items=0, has_next_page=False, items=[], raw={},
                ok=False, http_status=0, error_code="disabled", error="CompSniper disabled.",
            )
        if not self.api_key:
            HEALTH.status = BLOCKED_CREDENTIALS
            HEALTH.configured = False
            HEALTH.last_error = "COMPSNIPER_API_KEY is not set."
            HEALTH.last_error_code = "unauthorized"
            HEALTH.last_http_status = 401
            return CompSniperPage(
                keyword=keyword, page=page, total_items=0, has_next_page=False, items=[], raw={},
                ok=False, http_status=401, error_code="unauthorized", error="Missing API key.",
            )
        site = ebay_site if ebay_site in VALID_SITES else "ebay.co.uk"
        params: dict[str, Any] = {
            "keyword": keyword,
            "count": max(1, min(int(count), 240)),
            "page": max(1, int(page)),
            "ebaySite": site,
            "sold": "true" if sold else "false",
            "itemCondition": item_condition,
            "includeCompleteListing": "true",
            "includeCompletedListings": "true",
        }
        if category_id:
            params["categoryId"] = category_id
            params["category_id"] = category_id
        own_client = client is None
        client = client or httpx.AsyncClient(timeout=settings.request_timeout_seconds)
        try:
            response = await client.get(
                f"{BASE_URL}{SCRAPE_PATH}",
                headers=self._headers(),
                params=params,
            )
        except httpx.HTTPError as exc:
            HEALTH.reachable = False
            HEALTH.last_error = str(exc)[:300]
            HEALTH.status = DEGRADED
            HEALTH.last_error_code = "network"
            return CompSniperPage(
                keyword=keyword, page=page, total_items=0, has_next_page=False, items=[], raw={},
                ok=False, http_status=0, error_code="network", error=str(exc)[:300],
            )
        finally:
            if own_client:
                await client.aclose()

        HEALTH.reachable = True
        HEALTH.configured = True
        HEALTH.requests_today += 1
        _apply_headers(response.headers, response.status_code)
        body: dict[str, Any] = {}
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                body = parsed
        except Exception:
            body = {}
        code = str(body.get("code") or "") or None
        error = str(body.get("error") or "") or None
        if response.status_code == 401 or code == "unauthorized":
            HEALTH.status = BLOCKED_CREDENTIALS
            HEALTH.last_error = error or "unauthorized"
            HEALTH.last_error_code = "unauthorized"
            return CompSniperPage(
                keyword=keyword, page=page, total_items=0, has_next_page=False, items=[], raw=body,
                ok=False, http_status=response.status_code, error_code="unauthorized", error=error,
            )
        if response.status_code == 429 or code in {"rate_limited", "quota_exceeded"}:
            HEALTH.status = DEGRADED
            HEALTH.last_error = error or code
            HEALTH.last_error_code = code or "rate_limited"
            if code == "quota_exceeded":
                HEALTH.quota_remaining = 0
            return CompSniperPage(
                keyword=keyword, page=page, total_items=0, has_next_page=False, items=[], raw=body,
                ok=False, http_status=response.status_code, error_code=code or "rate_limited", error=error,
            )
        if response.status_code != 200:
            HEALTH.status = DEGRADED
            HEALTH.last_error = error or f"HTTP {response.status_code}"
            HEALTH.last_error_code = code or "http_error"
            return CompSniperPage(
                keyword=keyword, page=page, total_items=0, has_next_page=False, items=[], raw=body,
                ok=False, http_status=response.status_code, error_code=code or "http_error", error=error,
            )
        items: list[CompSniperItem] = []
        raw_items = body.get("items") or body.get("results") or body.get("listings") or []
        data = body.get("data")
        if isinstance(data, dict):
            raw_items = data.get("items") or data.get("results") or raw_items
        elif isinstance(data, list) and not raw_items:
            raw_items = data
        for raw_item in raw_items:
            parsed_item = parse_item(raw_item)
            if parsed_item is None:
                continue
            if sold and parsed_item.listing_type not in COMPLETED_LISTING_TYPES:
                continue
            items.append(parsed_item)
        HEALTH.status = LIVE
        HEALTH.last_success_at = _now()
        HEALTH.last_error = None
        HEALTH.last_error_code = None
        return CompSniperPage(
            keyword=str(body.get("keyword") or keyword),
            page=int(body.get("page") or page),
            total_items=int(body.get("totalItems") or len(items)),
            has_next_page=bool(body.get("hasNextPage")),
            items=items,
            raw=body,
            ok=True,
            http_status=200,
        )
