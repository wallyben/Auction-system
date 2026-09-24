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

    async def search(self, query: str, *, country: str = "IE") -> SearchResponse: ...


def brave_configured() -> bool:
    return bool(os.environ.get("BRAVE_SEARCH_API_KEY", "").strip())


def source_health() -> dict[str, dict[str, object]]:
    usage = {}
    try:
        usage = SearchBudget().usage()
    except OSError:
        usage = {}
    brave_status = "LIVE" if brave_configured() and search_enabled() else "NOT_CONFIGURED"
    if not search_enabled():
        brave_status = "DOWN"
    crawl = os.environ.get("CV_COMMON_CRAWL_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
    return {
        "autoza": {"name": "AUTOZA", "status": "NOT_RUN"},
        "brave": {
            "name": "BRAVE SEARCH",
            "status": brave_status,
            "requests_today": usage.get("requests_today", 0),
            "requests_this_month": usage.get("requests_this_month", 0),
        },
        "common_crawl": {"name": "COMMON CRAWL", "status": "LIVE" if crawl else "DOWN"},
    }


def search_enabled() -> bool:
    return os.environ.get("CV_MARKET_SEARCH_ENABLED", "true").strip().lower() not in {"0", "false", "no"}


class BraveMarketSearchProvider:
    name = "brave"

    def __init__(self, client: httpx.AsyncClient, api_key: str | None = None) -> None:
        self.client = client
        self.api_key = api_key if api_key is not None else os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()

    async def search(self, query: str, *, country: str = "IE") -> SearchResponse:
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
        self.group_cap = int(os.environ.get("CV_SEARCH_MAX_REQUESTS_PER_MARKET_GROUP", "12"))
        self.auction_cap = int(os.environ.get("CV_SEARCH_MAX_REQUESTS_PER_AUCTION", "120"))
        self.day_cap = int(os.environ.get("CV_SEARCH_MAX_REQUESTS_PER_DAY", "400"))
        self.cache_hours = int(os.environ.get("CV_SEARCH_MARKET_CACHE_HOURS", "12"))
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
