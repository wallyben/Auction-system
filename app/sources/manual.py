"""CSV, manual capture, and policy-blocked adapters."""

from __future__ import annotations

import csv
import hashlib
import io
from decimal import Decimal

from app.models.enums import SourceKind, SourceStatus
from app.sources.base import HealthProof, NormalizedListing, SourceAdapter


class CsvImportAdapter(SourceAdapter):
    source_id = "csv_import"
    display_name = "Owner CSV import"
    country = "IE"
    kind = SourceKind.MANUAL
    official_api = False
    access_method = "owner_csv"
    credentials_required = False
    cadence_minutes = 1440

    async def healthcheck(self) -> HealthProof:
        return HealthProof(
            status=SourceStatus.LIVE,
            ok=True,
            http_status=None,
            latency_ms=0,
            records=0,
            detail="CSV import is always available.",
            proof={"columns": ["source", "external_id", "url", "title", "price", "currency", "country", "condition"]},
        )

    async def search(self, query: str, *, limit: int = 20) -> list[NormalizedListing]:
        return []

    def parse(self, text: str) -> list[NormalizedListing]:
        reader = csv.DictReader(io.StringIO(text))
        out: list[NormalizedListing] = []
        for row in reader:
            ext = row.get("external_id") or hashlib.sha256(
                (row.get("url") or row.get("title") or "").encode()
            ).hexdigest()[:16]
            price = row.get("price") or row.get("asking_price")
            out.append(
                NormalizedListing(
                    source_id=row.get("source") or self.source_id,
                    external_id=ext,
                    url=row.get("url") or f"manual://{ext}",
                    title=row.get("title") or "",
                    description=row.get("description") or "",
                    seller=row.get("seller"),
                    country=(row.get("country") or "IE")[:2].upper(),
                    currency=(row.get("currency") or "EUR")[:3].upper(),
                    asking_price=Decimal(price) if price else None,
                    shipping_cost=Decimal(row["shipping"]) if row.get("shipping") else None,
                    condition_raw=row.get("condition"),
                    category=row.get("category"),
                    brand=row.get("brand"),
                    model=row.get("model"),
                    gtin=row.get("gtin") or row.get("ean"),
                    extras={"owner_import": True},
                    raw=dict(row),
                    source_confidence=Decimal("0.95"),
                )
            )
        return out


class ManualAdapter(SourceAdapter):
    source_id = "manual"
    display_name = "Manual listing"
    country = "IE"
    kind = SourceKind.MANUAL
    official_api = False
    access_method = "owner_form"
    credentials_required = False
    cadence_minutes = 1440

    async def healthcheck(self) -> HealthProof:
        return HealthProof(
            status=SourceStatus.LIVE,
            ok=True,
            http_status=None,
            latency_ms=0,
            records=0,
            detail="Manual capture is LIVE. Owner pastes a listing; ARIE does not fetch blocked sites.",
            proof={"mode": "owner_supplied"},
        )

    async def search(self, query: str, *, limit: int = 20) -> list[NormalizedListing]:
        return []


class BlockedAdapter(SourceAdapter):
    def __init__(
        self,
        source_id: str,
        display_name: str,
        country: str,
        reason: str,
        status: SourceStatus,
        fallback: str,
        cadence_minutes: int = 1440,
    ) -> None:
        self.source_id = source_id
        self.display_name = display_name
        self.country = country
        self.kind = SourceKind.ACQUISITION
        self.official_api = False
        self.access_method = "blocked"
        self.credentials_required = True
        self.cadence_minutes = cadence_minutes
        self.reason = reason
        self.status = status
        self.fallback = fallback

    async def healthcheck(self) -> HealthProof:
        return HealthProof(
            status=self.status,
            ok=False,
            http_status=None,
            latency_ms=None,
            records=0,
            detail=self.reason,
            proof={"fallback": self.fallback, "status": self.status.value},
        )

    async def search(self, query: str, *, limit: int = 20) -> list[NormalizedListing]:
        return []
