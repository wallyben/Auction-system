"""Realised-sale evidence. Asking prices never enter this path."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import EvidenceType
from app.models.orm import OwnerSale, SoldEvidence


@dataclass(slots=True)
class SoldEvidenceHit:
    source: str
    title: str
    sold_price_eur: Decimal
    territory: str
    condition: str
    channel: str
    sold_date: datetime
    evidence_type: EvidenceType
    quality: str
    url: str | None
    notes: str = ""


class SoldEvidenceProvider(Protocol):
    name: str

    async def search_realised_sales(
        self, product: str, market: str, condition: str, *, limit: int = 20
    ) -> list[SoldEvidenceHit]: ...

    async def healthcheck(self) -> dict[str, object]: ...

    async def freshness(self) -> datetime | None: ...


class IrishPanelProvider:
    name = "irish_panel"

    def __init__(self, session: Session) -> None:
        self.session = session

    async def search_realised_sales(
        self, product: str, market: str, condition: str, *, limit: int = 20
    ) -> list[SoldEvidenceHit]:
        needle = (product or "").lower()[:80]
        rows = self.session.scalars(
            select(SoldEvidence).order_by(SoldEvidence.sold_date.desc()).limit(200)
        ).all()
        hits: list[SoldEvidenceHit] = []
        for row in rows:
            hay = f"{row.canonical_product_id} {row.channel} {row.source}".lower()
            if needle and needle not in hay:
                continue
            if market and market.upper() not in {row.territory.upper(), "ALL", ""}:
                if row.territory.upper() not in {market.upper(), "IE"}:
                    continue
            hits.append(
                SoldEvidenceHit(
                    source=row.source,
                    title=row.canonical_product_id,
                    sold_price_eur=row.sold_price,
                    territory=row.territory,
                    condition=row.condition,
                    channel=row.channel,
                    sold_date=row.sold_date,
                    evidence_type=EvidenceType.REALISED_SALE,
                    quality=row.evidence_quality,
                    url=row.url_or_reference,
                    notes="Irish realised-price panel",
                )
            )
            if len(hits) >= limit:
                break
        return hits

    async def healthcheck(self) -> dict[str, object]:
        count = len(self.session.scalars(select(SoldEvidence).limit(500)).all())
        return {"provider": self.name, "rows": count, "ok": True}

    async def freshness(self) -> datetime | None:
        row = self.session.scalars(select(SoldEvidence).order_by(SoldEvidence.sold_date.desc()).limit(1)).first()
        return row.sold_date if row else None


class OwnerSalesProvider:
    name = "owner_sales"

    def __init__(self, session: Session) -> None:
        self.session = session

    async def search_realised_sales(
        self, product: str, market: str, condition: str, *, limit: int = 20
    ) -> list[SoldEvidenceHit]:
        needle = (product or "").lower()[:80]
        rows = self.session.scalars(select(OwnerSale).order_by(OwnerSale.sale_date.desc()).limit(200)).all()
        hits: list[SoldEvidenceHit] = []
        for row in rows:
            hay = f"{row.canonical_key} {row.product} {row.brand} {row.model}".lower()
            if needle and needle not in hay:
                continue
            hits.append(
                SoldEvidenceHit(
                    source="owner_recorded",
                    title=row.product,
                    sold_price_eur=row.sale_price,
                    territory=row.territory,
                    condition=row.condition,
                    channel=row.sale_platform or "owner",
                    sold_date=row.sale_date,
                    evidence_type=EvidenceType.OWNER_RECORDED,
                    quality="high",
                    url=None,
                    notes="Owner-recorded realised transaction. Highest local weight.",
                )
            )
            if len(hits) >= limit:
                break
        return hits

    async def healthcheck(self) -> dict[str, object]:
        count = len(self.session.scalars(select(OwnerSale).limit(500)).all())
        return {"provider": self.name, "rows": count, "ok": True}

    async def freshness(self) -> datetime | None:
        row = self.session.scalars(select(OwnerSale).order_by(OwnerSale.sale_date.desc()).limit(1)).first()
        return row.sale_date if row else None


async def search_sold_evidence(
    session: Session, product: str, market: str = "IE", condition: str = "", *, limit: int = 20
) -> list[SoldEvidenceHit]:
    hits: list[SoldEvidenceHit] = []
    for provider in (OwnerSalesProvider(session), IrishPanelProvider(session)):
        hits.extend(await provider.search_realised_sales(product, market, condition, limit=limit))
    hits.sort(key=lambda h: h.sold_date, reverse=True)
    return hits[:limit]


async def sold_provider_health(session: Session) -> list[dict[str, object]]:
    from app.sold.insights import EbayMarketplaceInsightsProvider

    rows = []
    for provider in (OwnerSalesProvider(session), IrishPanelProvider(session), EbayMarketplaceInsightsProvider()):
        rows.append(await provider.healthcheck())
    return rows


def empty_freshness() -> datetime:
    return datetime(1970, 1, 1, tzinfo=timezone.utc)
