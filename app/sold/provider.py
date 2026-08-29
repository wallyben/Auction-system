"""Realised-sale evidence. Asking prices never enter this path."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from sqlalchemy import func, select
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
    variant: str = ""
    currency: str = "EUR"
    shipping: Decimal | None = None
    identity_key: str = ""
    provenance: str = ""
    market: str = ""
    quantity: int = 1
    identity_confidence: Decimal | None = None
    matching_confidence: Decimal | None = None


class SoldEvidenceProvider(Protocol):
    name: str

    async def search_realised_sales(
        self, product: str, market: str, condition: str, *, limit: int = 20
    ) -> list[SoldEvidenceHit]: ...

    async def healthcheck(self) -> dict[str, object]: ...

    async def freshness(self) -> datetime | None: ...


def _hit_from_sold_row(row: SoldEvidence, notes: str) -> SoldEvidenceHit:
    extras = row.extras or {}
    shipping = row.shipping_charged
    return SoldEvidenceHit(
        source=row.source,
        title=str(extras.get("title") or row.canonical_product_id),
        sold_price_eur=row.sold_price,
        territory=row.territory,
        condition=row.condition,
        channel=row.channel,
        sold_date=row.sold_date,
        evidence_type=EvidenceType.REALISED_SALE if row.source not in {"owner_recorded", "owner_sales", "ebay_owner_fulfillment"} else EvidenceType.OWNER_RECORDED,
        quality=row.evidence_quality,
        url=row.url_or_reference,
        notes=notes,
        variant=str(extras.get("variant") or ""),
        currency=row.currency or "EUR",
        shipping=shipping,
        identity_key=row.canonical_product_id,
        provenance=str(extras.get("provenance") or row.source),
        market=str(extras.get("market") or row.territory),
        quantity=int(extras.get("quantity") or 1),
        identity_confidence=Decimal(str(extras["identity_confidence"])) if extras.get("identity_confidence") not in (None, "") else None,
        matching_confidence=Decimal(str(extras["matching_confidence"])) if extras.get("matching_confidence") not in (None, "") else None,
    )


class IrishPanelProvider:
    name = "irish_panel"

    def __init__(self, session: Session) -> None:
        self.session = session

    async def search_realised_sales(
        self, product: str, market: str, condition: str, *, limit: int = 20
    ) -> list[SoldEvidenceHit]:
        needle = (product or "").lower()[:80]
        ident = (product or "").strip()
        canonical_query = ident.count("|") >= 2
        stmt = select(SoldEvidence).order_by(SoldEvidence.sold_date.desc())
        if canonical_query:
            stmt = stmt.where(SoldEvidence.canonical_product_id == ident)
            stmt = stmt.limit(max(limit * 2, 80))
        else:
            stmt = stmt.limit(400)
        rows = self.session.scalars(stmt).all()
        hits: list[SoldEvidenceHit] = []
        for row in rows:
            extras = row.extras or {}
            hay = " ".join(
                [
                    row.canonical_product_id,
                    row.channel,
                    row.source,
                    str(extras.get("title") or ""),
                    str(extras.get("variant") or ""),
                    str(extras.get("product_identity") or ""),
                ]
            ).lower()
            if canonical_query:
                pass
            elif ident and row.canonical_product_id.lower() == ident.lower():
                pass
            elif needle and needle not in hay:
                tokens = [part for part in needle.replace("-", " ").split() if len(part) > 2]
                if tokens and not all(token in hay for token in tokens[:3]):
                    continue
            if (row.source or "") in {"owner_recorded", "owner_sales", "ebay_owner_fulfillment", "owner_trade_floor"}:
                continue
            if extras.get("ticket_level") is False:
                continue
            if extras.get("accepted_for_valuation") is False:
                continue
            if str(extras.get("evidence_class") or "") in {"E", "F", "G", "X"}:
                continue
            # Stored camera tickets were identity-gated at ingest/revalidate.
            # Do not rematch every ticket per listing (that pinned the single worker).
            if not canonical_query:
                from app.sold.match import variant_reject

                if product and variant_reject(product, str(extras.get("title") or row.canonical_product_id)):
                    continue
            if market and market.upper() not in {row.territory.upper(), "ALL", ""}:
                if row.territory.upper() not in {market.upper(), "IE", "GB", "DE", "FR", "IT", "ES", "NL"}:
                    continue
            hits.append(_hit_from_sold_row(row, "Persisted realised-price panel. Not an asking price."))
            if len(hits) >= limit:
                break
        return hits

    async def healthcheck(self) -> dict[str, object]:
        count = int(self.session.scalar(select(func.count()).select_from(SoldEvidence)) or 0)
        return {"provider": self.name, "rows": count, "ok": True, "classification": "REALIZED_SOLD"}

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
        rows = self.session.scalars(select(OwnerSale).order_by(OwnerSale.sale_date.desc()).limit(400)).all()
        hits: list[SoldEvidenceHit] = []
        for row in rows:
            hay = f"{row.canonical_key} {row.product} {row.brand} {row.model} {row.variant or ''}".lower()
            if needle and needle not in hay:
                tokens = [part for part in needle.replace("-", " ").split() if len(part) > 2]
                if tokens and not all(token in hay for token in tokens[:3]):
                    continue
            from app.sold.match import variant_reject

            if product and variant_reject(product, row.product):
                continue
            trade = (row.raw or {}).get("trade_floor")
            notes = "Owner-recorded realised transaction. Highest local weight."
            if trade:
                notes += " Trade floor present as downside-only evidence."
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
                    notes=notes,
                    variant=row.variant or "",
                    currency=row.currency or "EUR",
                    shipping=row.shipping_out or None,
                    identity_key=row.canonical_key,
                    provenance="owner_csv_or_oauth",
                    market=row.territory,
                )
            )
            if trade:
                try:
                    floor = Decimal(str(trade).replace(",", "").replace("€", "").strip())
                except Exception:
                    floor = Decimal("0")
                if floor > 0:
                    hits.append(
                        SoldEvidenceHit(
                            source="owner_trade_floor",
                            title=row.product,
                            sold_price_eur=floor,
                            territory=row.territory,
                            condition=row.condition,
                            channel="trade_floor",
                            sold_date=row.sale_date,
                            evidence_type=EvidenceType.TRADE_IN,
                            quality="medium",
                            url=None,
                            notes="Owner-supplied trade-buy / liquidation floor. Downside evidence only.",
                            variant=row.variant or "",
                            currency=row.currency or "EUR",
                            identity_key=row.canonical_key,
                            provenance="owner_trade_floor",
                            market=row.territory,
                        )
                    )
            if len(hits) >= limit:
                break
        return hits

    async def healthcheck(self) -> dict[str, object]:
        count = len(self.session.scalars(select(OwnerSale).limit(500)).all())
        return {"provider": self.name, "rows": count, "ok": True, "classification": "REALIZED_SOLD"}

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
    from app.evidence.providers.compsniper import compsniper_health
    from app.sold.ebay_owner_oauth import EbayOwnerOrdersProvider
    from app.sold.insights import EbayMarketplaceInsightsProvider

    rows = []
    for provider in (
        OwnerSalesProvider(session),
        IrishPanelProvider(session),
        EbayMarketplaceInsightsProvider(),
        EbayOwnerOrdersProvider(),
    ):
        rows.append(await provider.healthcheck())
    rows.append(compsniper_health())
    return rows


def empty_freshness() -> datetime:
    return datetime(1970, 1, 1, tzinfo=timezone.utc)
