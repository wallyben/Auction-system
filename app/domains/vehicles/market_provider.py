"""Search-index providers. Brave is the first implementation.

Calls use the documented Web Search endpoint. Invalid keys and exhausted
quotas are not retried. Transient 429 and 5xx responses are.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.core import config

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
PARSER_VERSION = "brave-market-1"


class SearchNotConfigured(RuntimeError):
    pass


class SearchRejected(RuntimeError):
    def __init__(self, status: str, detail: str) -> None:
        self.status = status
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class SearchHit:
    url: str
    title: str
    description: str
    extra_snippets: tuple[str, ...]
    page_age: str | None
    age: str | None
    domain: str


@dataclass(slots=True)
class SearchResponse:
    provider: str
    query: str
    retrieved_at: datetime
    hits: list[SearchHit] = field(default_factory=list)
    more: bool = False
    error: str = ""


class MarketSearchProvider(Protocol):
    name: str

    async def search(self, query: str, *, country: str = "ALL") -> SearchResponse: ...


def brave_api_key() -> str:
    return (config.settings.brave_search_api_key or "").strip()


def brave_configured() -> bool:
    return bool(brave_api_key())


def source_health() -> dict[str, dict[str, object]]:
    usage = {}
    try:
        usage = SearchBudget().usage()
    except OSError:
        usage = {}
    brave_status = "LIVE" if brave_configured() and search_enabled() else "NOT_CONFIGURED"
    if not search_enabled():
        brave_status = "DOWN"
    return {
        "autoza": {"name": "AUTOZA", "status": "NOT_RUN"},
        "brave": {
            "name": "BRAVE SEARCH",
            "status": brave_status,
            "configured": brave_configured(),
            "requests_today": usage.get("requests_today", 0),
            "requests_this_month": usage.get("requests_this_month", 0),
        },
        "common_crawl": {"name": "COMMON CRAWL", "status": "LIVE" if config.settings.cv_common_crawl_enabled else "DOWN"},
        "donedeal_browser": _browser_health("DONEDEAL BROWSER", "browser-donedeal-1"),
        "carsireland_browser": _browser_health("CARSIRELAND BROWSER", "browser-carsireland-1"),
        "carzone_browser": _browser_health("CARZONE BROWSER", "browser-carzone-1"),
        "dealer_browser": _browser_health("GENERIC DEALER BROWSER", "browser-dealer-1"),
    }


def search_enabled() -> bool:
    return bool(config.settings.cv_market_search_enabled)


def _browser_health(name: str, source_id: str) -> dict[str, object]:
    from app.domains.vehicles.browser_market import RIGHTS_STATUS, TECHNICAL_STATUS
    from app.domains.vehicles.browser_market.cache import read_group_snapshot

    status = "NOT_TESTED"
    for row in read_group_snapshot():
        sources = row.get("sources") or {}
        item = sources.get(source_id) or {}
        found = str(item.get("status") or "")
        if found:
            status = found
            break
    if not config.settings.cv_browser_enabled:
        status = "DISABLED"
    return {
        "name": name,
        "status": status,
        "technical_status": TECHNICAL_STATUS,
        "rights_status": RIGHTS_STATUS,
        "evidence_class": "PUBLIC_PAGE_CURRENT_UNLICENSED",
    }


class BraveMarketSearchProvider:
    name = "brave"

    def __init__(self, client: httpx.AsyncClient, api_key: str | None = None) -> None:
        self.client = client
        self.api_key = brave_api_key() if api_key is None else api_key.strip()

    async def search(self, query: str, *, country: str = "ALL") -> SearchResponse:
        if not self.api_key:
            raise SearchNotConfigured("BRAVE_SEARCH_API_KEY is not set")
        params = {
            "q": query,
            "country": country,
            "search_lang": "en",
            "count": "10",
            "extra_snippets": "true",
            "safesearch": "off",
        }
        headers = {"X-Subscription-Token": self.api_key, "Accept": "application/json"}
        last_error = ""
        for attempt in range(3):
            try:
                response = await self.client.get(BRAVE_ENDPOINT, params=params, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = str(exc)
                continue
            if response.status_code in {401, 403}:
                raise SearchRejected("NOT_CONFIGURED", "Brave rejected the API key")
            if response.status_code == 400:
                raise SearchRejected("DOWN", "Brave rejected the query")
            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
                continue
            if response.status_code != 200:
                raise SearchRejected("DOWN", f"Brave HTTP {response.status_code}")
            payload = response.json()
            return _parse_brave(query, payload)
        raise SearchRejected("DEGRADED", last_error or "Brave request failed")


def _parse_brave(query: str, payload: dict[str, Any]) -> SearchResponse:
    web = payload.get("web") or {}
    hits: list[SearchHit] = []
    for row in web.get("results") or []:
        url = str(row.get("url") or "")
        if not url:
            continue
        extras = tuple(str(item) for item in (row.get("extra_snippets") or []) if item)
        hits.append(
            SearchHit(
                url=url,
                title=str(row.get("title") or ""),
                description=str(row.get("description") or ""),
                extra_snippets=extras,
                page_age=row.get("page_age") or None,
                age=row.get("age") or None,
                domain=_domain(url),
            )
        )
    more = bool((payload.get("query") or {}).get("more_results_available"))
    return SearchResponse("brave", query, datetime.now(timezone.utc), hits, more)


def _domain(url: str) -> str:
    host = url.split("/")[2] if "://" in url else ""
    return host.lower().removeprefix("www.")


class SearchBudget:
    """Hard caps. They are not targets."""

    def __init__(self, path: Path | None = None) -> None:
        root = path or Path(os.environ.get("CV_MARKET_STATE_DIR", "artifacts/runtime/market_search"))
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "usage.json"
        self.cache_path = root / "query_cache.json"
        self.group_cap = int(config.settings.cv_search_max_requests_per_market_group)
        self.auction_cap = int(config.settings.cv_search_max_requests_per_auction)
        self.day_cap = int(config.settings.cv_search_max_requests_per_day)
        self.cache_hours = int(config.settings.cv_search_market_cache_hours)
        self.data = self._load(self.path)
        self.cache = self._load(self.cache_path)

    def allow(self, *, group_id: str, auction_id: str) -> bool:
        today, month = _periods()
        if int(self.data.get("day", {}).get(today, 0)) >= self.day_cap:
            return False
        if int(self.data.get("groups", {}).get(group_id, 0)) >= self.group_cap:
            return False
        if int(self.data.get("auctions", {}).get(auction_id, 0)) >= self.auction_cap:
            return False
        return True

    def record(self, *, group_id: str, auction_id: str) -> None:
        today, month = _periods()
        self.data.setdefault("day", {})
        self.data.setdefault("month", {})
        self.data.setdefault("groups", {})
        self.data.setdefault("auctions", {})
        self.data["day"][today] = int(self.data["day"].get(today, 0)) + 1
        self.data["month"][month] = int(self.data["month"].get(month, 0)) + 1
        self.data["groups"][group_id] = int(self.data["groups"].get(group_id, 0)) + 1
        self.data["auctions"][auction_id] = int(self.data["auctions"].get(auction_id, 0)) + 1
        self._save(self.path, self.data)

    def cached(self, query: str) -> dict[str, Any] | None:
        key = hashlib.sha256(query.encode("utf-8")).hexdigest()
        row = self.cache.get(key)
        if not row:
            return None
        retrieved = datetime.fromisoformat(str(row["retrieved_at"]))
        age = datetime.now(timezone.utc) - retrieved
        if age.total_seconds() > self.cache_hours * 3600:
            return None
        return row

    def store(self, query: str, response: SearchResponse) -> None:
        key = hashlib.sha256(query.encode("utf-8")).hexdigest()
        self.cache[key] = {
            "query": query,
            "provider": response.provider,
            "retrieved_at": response.retrieved_at.isoformat(),
            "hits": [
                {
                    "url": hit.url,
                    "title": hit.title,
                    "description": hit.description,
                    "extra_snippets": list(hit.extra_snippets),
                    "page_age": hit.page_age,
                    "age": hit.age,
                    "domain": hit.domain,
                }
                for hit in response.hits
            ],
            "hash": key,
        }
        self._save(self.cache_path, self.cache)

    def usage(self, auction_id: str = "") -> dict[str, int]:
        today, month = _periods()
        return {
            "requests_today": int(self.data.get("day", {}).get(today, 0)),
            "requests_this_month": int(self.data.get("month", {}).get(month, 0)),
            "requests_for_auction": int(self.data.get("auctions", {}).get(auction_id, 0)),
        }

    def _load(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")


def _periods() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return now.date().isoformat(), now.strftime("%Y-%m")
