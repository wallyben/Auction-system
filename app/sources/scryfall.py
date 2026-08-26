"""Scryfall comparable adapter. Official API; EUR prices are market guides, not Irish realised sales."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from app.core.http import build_client, request_json
from app.core.logging import get_logger
from app.models.enums import EvidenceType, SourceKind, SourceStatus
from app.sources.base import HealthProof, NormalizedListing, SourceAdapter

logger = get_logger("arie.sources.scryfall")
SCRYFALL_NAMED = "https://api.scryfall.com/cards/named"
SCRYFALL_SEARCH = "https://api.scryfall.com/cards/search"


class ScryfallAdapter(SourceAdapter):
    source_id = "scryfall"
    display_name = "Scryfall / Cardmarket guide"
    country = "EU"
    kind = SourceKind.COMPARABLE
    official_api = True
    access_method = "official_public_json"
    credentials_required = False
    cadence_minutes = 180

    async def healthcheck(self) -> HealthProof:
        started = time.perf_counter()
        try:
            async with build_client() as client:
                response, payload = await request_json(
                    client,
                    "GET",
                    SCRYFALL_NAMED,
                    params={"exact": "Sol Ring"},
                )
            prices = payload.get("prices") or {}
            return HealthProof(
                status=SourceStatus.LIVE,
                ok=True,
                http_status=response.status_code,
                latency_ms=int((time.perf_counter() - started) * 1000),
                records=1,
                detail="Scryfall card + EUR guide price retrieved. This is dealer/market evidence, not a realised Irish sale.",
                proof={
                    "id": payload.get("id"),
                    "name": payload.get("name"),
                    "eur": prices.get("eur"),
                    "usd": prices.get("usd"),
                    "scryfall_uri": payload.get("scryfall_uri"),
                    "evidence_type": EvidenceType.DEALER_RETAIL.value,
                },
            )
        except Exception as exc:
            logger.warning("scryfall_health_failed", error=str(exc))
            return HealthProof(
                status=SourceStatus.BLOCKED_TECHNICAL,
                ok=False,
                http_status=None,
                latency_ms=int((time.perf_counter() - started) * 1000),
                records=0,
                detail=str(exc),
                proof={},
            )

    async def search(self, query: str, *, limit: int = 20) -> list[NormalizedListing]:
        from app.core.http import SourceHttpError

        try:
            async with build_client() as client:
                _, payload = await request_json(
                    client,
                    "GET",
                    SCRYFALL_SEARCH,
                    params={"q": query, "unique": "prints"},
                )
        except SourceHttpError as exc:
            if exc.status_code == 404:
                return []
            raise
        return [self._normalize(card) for card in (payload.get("data") or [])[:limit]]

    def _normalize(self, card: dict[str, Any]) -> NormalizedListing:
        prices = card.get("prices") or {}
        eur = prices.get("eur")
        purchase = (card.get("purchase_uris") or {}).get("cardmarket")
        image = (card.get("image_uris") or {}).get("normal")
        return NormalizedListing(
            source_id=self.source_id,
            external_id=str(card.get("id")),
            url=str(card.get("scryfall_uri") or purchase or ""),
            title=str(card.get("name") or ""),
            description=str(card.get("type_line") or ""),
            country="EU",
            currency="EUR",
            asking_price=Decimal(str(eur)) if eur else None,
            condition_raw="Near Mint guide",
            category="trading_cards",
            brand="Wizards of the Coast",
            model=str(card.get("name") or ""),
            variant=str(card.get("set_name") or ""),
            images=[image] if image else [],
            extras={
                "evidence_type": EvidenceType.DEALER_RETAIL.value,
                "prices": prices,
            },
            raw=card,
            source_confidence=Decimal("0.80"),
        )
