"""Owner-configured RSS/Atom adapter. LIVE only when a real feed returns entries."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import feedparser

from app.core.config import settings
from app.core.http import build_client, request_json
from app.core.logging import get_logger
from app.models.enums import SourceKind, SourceStatus
from app.sources.base import HealthProof, NormalizedListing, SourceAdapter

logger = get_logger("arie.sources.rss")


def _money_from_text(text: str) -> Decimal | None:
    import re

    match = re.search(r"(?:€|EUR|£|GBP|\$)\s?([0-9]+(?:[.,][0-9]{1,2})?)", text or "", re.I)
    if not match:
        return None
    return Decimal(match.group(1).replace(",", "."))


class RssAdapter(SourceAdapter):
    source_id = "rss_generic"
    display_name = "Configured RSS/Atom feeds"
    country = "EU"
    kind = SourceKind.ACQUISITION
    official_api = False
    access_method = "owner_rss"
    credentials_required = False
    cadence_minutes = 30

    def __init__(self, urls: list[str] | None = None) -> None:
        self._urls = urls

    def _url_list(self) -> list[str]:
        return list(self._urls) if self._urls is not None else settings.rss_url_list()

    async def healthcheck(self) -> HealthProof:
        urls = self._url_list()
        if not urls:
            return HealthProof(
                status=SourceStatus.DISABLED,
                ok=False,
                http_status=None,
                latency_ms=0,
                records=0,
                detail="No RSS_URLS configured. Parser is implemented; owner must supply permitted feed URLs.",
                proof={"parser": "feedparser", "configured_urls": 0},
            )
        started = time.perf_counter()
        try:
            items = await self.search("", limit=5)
            return HealthProof(
                status=SourceStatus.LIVE if items else SourceStatus.DEGRADED,
                ok=bool(items),
                http_status=200,
                latency_ms=int((time.perf_counter() - started) * 1000),
                records=len(items),
                detail="RSS/Atom feed parsed." if items else "Feed fetched but contained no entries.",
                proof={"urls": urls[:5], "sample": items[0].url if items else None},
            )
        except Exception as exc:
            logger.warning("rss_health_failed", error=str(exc))
            return HealthProof(
                status=SourceStatus.BLOCKED_TECHNICAL,
                ok=False,
                http_status=None,
                latency_ms=int((time.perf_counter() - started) * 1000),
                records=0,
                detail=str(exc),
                proof={"urls": urls[:5]},
            )

    async def search(self, query: str, *, limit: int = 20) -> list[NormalizedListing]:
        urls = self._url_list()
        if not urls:
            return []
        listings: list[NormalizedListing] = []
        async with build_client() as client:
            for url in urls:
                _, payload = await request_json(client, "GET", url)
                text = payload if isinstance(payload, str) else str(payload)
                listings.extend(self.parse_feed(text, url))
                if len(listings) >= limit:
                    break
        q = (query or "").lower()
        if q:
            listings = [item for item in listings if q in item.title.lower()]
        return listings[:limit]

    def parse_feed(self, xml: str, feed_url: str) -> list[NormalizedListing]:
        parsed = feedparser.parse(xml)
        out: list[NormalizedListing] = []
        for entry in parsed.entries or []:
            title = str(entry.get("title") or "")
            link = str(entry.get("link") or feed_url)
            summary = str(entry.get("summary") or entry.get("description") or "")
            ext = str(entry.get("id") or link)
            price = _money_from_text(f"{title} {summary}")
            out.append(
                NormalizedListing(
                    source_id=self.source_id,
                    external_id=ext[:180],
                    url=link,
                    title=title,
                    description=summary,
                    country="UN",
                    currency="EUR",
                    asking_price=price,
                    extras={"feed_url": feed_url, "evidence_type": "current_asking"},
                    raw={"title": title, "link": link},
                    source_confidence=Decimal("0.55"),
                    observed_at=datetime.now(timezone.utc),
                )
            )
        return out


RssAdapter = RssAdapter
