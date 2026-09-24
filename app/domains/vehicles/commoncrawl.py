"""Common Crawl enrichment. Indexes are discovered, never hardcoded.

Archived HTML is parsed in memory and discarded. The marketplace is not fetched.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

COLLINFO = "https://index.commoncrawl.org/collinfo.json"
DATA_HOST = "https://data.commoncrawl.org"
PARSER_VERSION = "commoncrawl-market-1"
RECENT_DAYS = 45


@dataclass(frozen=True, slots=True)
class ArchiveCapture:
    status: str
    url: str
    crawl_timestamp: datetime | None
    title: str
    facts: dict[str, str]
    error: str = ""


def crawl_enabled() -> bool:
    return os.environ.get("CV_COMMON_CRAWL_ENABLED", "true").strip().lower() not in {"0", "false", "no"}


class CommonCrawlMarketEnricher:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self._indexes: list[str] | None = None

    async def indexes(self) -> list[str]:
        if self._indexes is not None:
            return self._indexes
        response = await self.client.get(COLLINFO)
        response.raise_for_status()
        rows = response.json()
        names = [str(row["id"]) for row in rows if row.get("id")]
        self._indexes = names
        return names

    async def enrich(self, url: str) -> ArchiveCapture:
        if not crawl_enabled():
            return ArchiveCapture("ARCHIVE_MISS", url, None, "", {}, "disabled")
        try:
            names = await self.indexes()
        except (httpx.HTTPError, ValueError) as exc:
            return ArchiveCapture("ARCHIVE_MISS", url, None, "", {}, str(exc))
        for name in names[:4]:
            capture = await self._lookup(name, url)
            if capture is not None:
                return capture
        return ArchiveCapture("ARCHIVE_MISS", url, None, "", {})

    async def _lookup(self, index_id: str, url: str) -> ArchiveCapture | None:
        endpoint = f"https://index.commoncrawl.org/{index_id}-index"
        try:
            response = await self.client.get(endpoint, params={"url": url, "output": "json", "limit": "1"})
        except httpx.HTTPError:
            return None
        if response.status_code != 200 or not response.text.strip():
            return None
        line = response.text.strip().splitlines()[0]
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            return None
        filename = str(row.get("filename") or "")
        if not filename:
            return None
        offset = int(row.get("offset") or 0)
        length = int(row.get("length") or 0)
        stamp = _stamp(str(row.get("timestamp") or ""))
        html = await self._warc(filename, offset, length)
        if not html:
            return None
        title, facts = _facts(html)
        status = "ARCHIVE_RECENT" if stamp and datetime.now(timezone.utc) - stamp <= timedelta(days=RECENT_DAYS) else "ARCHIVE_HISTORICAL"
        return ArchiveCapture(status, url, stamp, title, facts)

    async def _warc(self, filename: str, offset: int, length: int) -> str:
        headers = {}
        if length > 0:
            headers["Range"] = f"bytes={offset}-{offset + length - 1}"
        try:
            response = await self.client.get(f"{DATA_HOST}/{filename}", headers=headers)
        except httpx.HTTPError:
            return ""
        if response.status_code not in {200, 206}:
            return ""
        text = response.content.decode("utf-8", errors="replace")
        parts = text.split("\r\n\r\n", 2)
        return parts[-1][:200_000]


def _stamp(value: str) -> datetime | None:
    if len(value) < 14 or not value[:14].isdigit():
        return None
    return datetime.strptime(value[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def _facts(html: str) -> tuple[str, dict[str, str]]:
    title = _tag(html, "title")
    facts: dict[str, str] = {}
    og = re.search(r'property="og:title"\s+content="([^"]+)"', html, re.I)
    if og:
        facts["og:title"] = _clean(og.group(1))
    for match in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.I | re.S):
        blob = match.group(1).strip()
        try:
            payload: Any = json.loads(blob)
        except json.JSONDecodeError:
            continue
        _walk_jsonld(payload, facts)
        break
    price = re.search(r"(?:€|EUR)\s*[0-9][0-9,]{2,}", html)
    if price and "price" not in facts:
        facts["price"] = _clean(price.group(0))
    return title, facts


def _walk_jsonld(payload: Any, facts: dict[str, str]) -> None:
    if isinstance(payload, list):
        for item in payload[:3]:
            _walk_jsonld(item, facts)
        return
    if not isinstance(payload, dict):
        return
    for key in ("name", "vehicleModelDate", "mileageFromOdometer", "price", "priceCurrency"):
        value = payload.get(key)
        if isinstance(value, (str, int, float)) and key not in facts:
            facts[key] = str(value)[:180]
        elif isinstance(value, dict) and "value" in value and key not in facts:
            facts[key] = str(value.get("value"))[:180]
    offers = payload.get("offers")
    if isinstance(offers, dict):
        _walk_jsonld(offers, facts)


def _tag(html: str, name: str) -> str:
    match = re.search(rf"<{name}[^>]*>(.*?)</{name}>", html, re.I | re.S)
    return _clean(match.group(1)) if match else ""


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()[:240]
