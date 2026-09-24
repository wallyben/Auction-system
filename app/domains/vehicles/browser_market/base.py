"""Shared card DTO. Adapters do not invent missing facts."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(slots=True)
class ListingCard:
    url: str
    listing_class: str
    title: str
    source_id: str
    manufacturer: str = ""
    model_family: str = ""
    variant: str = ""
    derivative: str = ""
    year: int | None = None
    registration_year: int | None = None
    mileage_km: int | None = None
    mileage_unit: str = ""
    engine: str = ""
    fuel: str = ""
    transmission: str = ""
    body: str = "UNKNOWN"
    wheelbase: str = ""
    roof: str = ""
    asking_price_eur: Decimal | None = None
    currency: str = ""
    vat_classification: str = "VAT_UNKNOWN"
    vat_fragment: str = ""
    vat_presentation: str = "unknown"
    price_evidence: str = ""
    price_status: str = "PRICE_UNKNOWN"
    mileage_evidence: str = ""
    dealer: str = ""
    location: str = ""
    geography: str = "UNKNOWN"
    geography_evidence: str = ""
    registration: str = ""
    rejection: str = ""
    evidence: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class PageFetch:
    url: str
    final_url: str
    status_code: int
    html: str
    challenge: str = ""
    error: str = ""


@dataclass(slots=True)
class SourcePageResult:
    source_id: str
    pages_opened: int = 0
    cards: int = 0
    accepted: int = 0
    rejected: int = 0
    vat_known: int = 0
    enriched: int = 0
    challenge: str = ""
    status: str = "NOT_TESTED"
    urls: list[str] = field(default_factory=list)
