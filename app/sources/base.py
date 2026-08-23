"""Source adapter contract and normalized listing DTO."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.models.enums import SourceKind, SourceStatus


@dataclass(slots=True)
class HealthProof:
    status: SourceStatus
    ok: bool
    http_status: int | None
    latency_ms: int | None
    records: int
    detail: str
    proof: dict[str, Any]
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class NormalizedListing:
    source_id: str
    external_id: str
    url: str
    title: str
    description: str = ""
    seller: str | None = None
    seller_type: str | None = None
    seller_location: str | None = None
    country: str = "UN"
    currency: str = "EUR"
    asking_price: Decimal | None = None
    current_bid: Decimal | None = None
    buy_now_price: Decimal | None = None
    shipping_cost: Decimal | None = None
    shipping_currency: str | None = None
    buyer_premium_percent: Decimal | None = None
    tax_included: bool | None = None
    condition_raw: str | None = None
    category: str | None = None
    brand: str | None = None
    model: str | None = None
    variant: str | None = None
    gtin: str | None = None
    mpn: str | None = None
    quantity: int = 1
    lot_size: int = 1
    listing_type: str = "fixed"
    ends_at: datetime | None = None
    images: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    source_confidence: Decimal = Decimal("0.70")
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SourceAdapter(ABC):
    source_id: str
    display_name: str
    country: str
    kind: SourceKind
    official_api: bool
    access_method: str
    credentials_required: bool
    cadence_minutes: int

    @abstractmethod
    async def healthcheck(self) -> HealthProof:
        raise NotImplementedError

    @abstractmethod
    async def search(self, query: str, *, limit: int = 20) -> list[NormalizedListing]:
        raise NotImplementedError

    async def fetch_listing(self, external_id: str) -> NormalizedListing | None:
        return None

    async def incremental_scan(self, query: str = "", *, limit: int = 20) -> list[NormalizedListing]:
        """Default incremental scan is a bounded search. Adapters may override."""
        return await self.search(query, limit=limit)


HealthProof = HealthProof
SourceAdapter = SourceAdapter
