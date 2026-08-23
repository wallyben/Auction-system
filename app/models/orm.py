"""SQLAlchemy models for ARIE production persistence."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.auction_lot import AuctionLot


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Source(Base, TimestampMixin):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    country: Mapped[str] = mapped_column(String(8), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    official_api: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    access_method: Mapped[str] = mapped_column(String(128), nullable=False)
    credentials_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DISABLED")
    status_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cadence_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_proof_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_ingested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    health_events: Mapped[list[SourceHealth]] = relationship(back_populates="source")


class SourceHealth(Base):
    __tablename__ = "source_health"
    __table_args__ = (Index("ix_source_health_source_checked", "source_id", "checked_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    proof: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    source: Mapped[Source] = relationship(back_populates="health_events")


class RawListing(Base, TimestampMixin):
    __tablename__ = "raw_listings"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_raw_listings_source_external"),
        Index("ix_raw_listings_fetched", "fetched_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class Listing(Base, TimestampMixin):
    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_listings_source_external"),
        Index("ix_listings_fingerprint", "fingerprint"),
        Index("ix_listings_status_seen", "status", "last_seen_at"),
        Index("ix_listings_gtin", "gtin"),
        Index("ix_listings_category", "category"),
        Index("ix_listings_country", "country"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    raw_listing_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_listings.id"))
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    seller: Mapped[str | None] = mapped_column(String(256))
    seller_type: Mapped[str | None] = mapped_column(String(64))
    seller_location: Mapped[str | None] = mapped_column(String(256))
    country: Mapped[str] = mapped_column(String(8), nullable=False, default="UN")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    asking_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    current_bid: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    buy_now_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    shipping_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    shipping_currency: Mapped[str | None] = mapped_column(String(3))
    buyer_premium_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    tax_included: Mapped[bool | None] = mapped_column(Boolean)
    condition_raw: Mapped[str | None] = mapped_column(String(256))
    condition_grade: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    category: Mapped[str | None] = mapped_column(String(128))
    brand: Mapped[str | None] = mapped_column(String(128))
    model: Mapped[str | None] = mapped_column(String(256))
    variant: Mapped[str | None] = mapped_column(String(256))
    gtin: Mapped[str | None] = mapped_column(String(32))
    mpn: Mapped[str | None] = mapped_column(String(64))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lot_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    listing_type: Mapped[str] = mapped_column(String(32), nullable=False, default="fixed")
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.5"))
    extras: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    images: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"), index=True)


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_brand_model", "brand", "model"),
        Index("ix_products_gtin", "gtin"),
        UniqueConstraint("canonical_key", name="uq_products_canonical_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    canonical_key: Mapped[str] = mapped_column(String(512), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(128))
    family: Mapped[str | None] = mapped_column(String(256))
    model: Mapped[str | None] = mapped_column(String(256))
    variant: Mapped[str | None] = mapped_column(String(256))
    category: Mapped[str | None] = mapped_column(String(128))
    gtin: Mapped[str | None] = mapped_column(String(32))
    mpn: Mapped[str | None] = mapped_column(String(64))
    identity_level: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    identity_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class ProductIdentityLink(Base):
    __tablename__ = "product_identity_links"
    __table_args__ = (Index("ix_identity_links_listing", "listing_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ListingComponent(Base):
    __tablename__ = "listing_components"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id"), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(String(128))
    model: Mapped[str | None] = mapped_column(String(256))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    estimated_value_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    sellable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Comparable(Base, TimestampMixin):
    __tablename__ = "comparables"
    __table_args__ = (
        Index("ix_comparables_product", "product_id"),
        Index("ix_comparables_listing", "subject_listing_id"),
        Index("ix_comparables_observed", "observed_at"),
        Index("ix_comparables_fingerprint", "fingerprint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    subject_listing_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("listings.id"))
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    condition_grade: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    country: Mapped[str] = mapped_column(String(8), nullable=False, default="UN")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    shipping: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    adjusted_price_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    listed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    product_match_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    condition_match_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    evidence_weight: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0"))
    outlier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    adjustment_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    extras: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("base", "quote", "as_of", name="uq_fx_rates_pair_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    base: Mapped[str] = mapped_column(String(3), nullable=False)
    quote: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TaxRule(Base, TimestampMixin):
    __tablename__ = "tax_rules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    jurisdiction: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    rule_class: Mapped[str] = mapped_column(String(32), nullable=False)
    rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_url: Mapped[str] = mapped_column(Text, nullable=False)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Valuation(Base, TimestampMixin):
    __tablename__ = "valuations"
    __table_args__ = (Index("ix_valuations_listing", "listing_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id"), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_sale_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    quick_sale_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    high_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    low_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    comparable_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    realised_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    local_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    foreign_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expected_days_to_sale: Mapped[int | None] = mapped_column(Integer)
    liquidity_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    valued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Opportunity(Base, TimestampMixin):
    __tablename__ = "opportunities"
    __table_args__ = (
        Index("ix_opportunities_decision_score", "decision", "score"),
        Index("ix_opportunities_listing", "listing_id"),
        UniqueConstraint("listing_id", name="uq_opportunities_listing"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id"), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    valuation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("valuations.id"))
    decision: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    expected_profit_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    expected_roi: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    margin_percent: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    downside_profit_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    upside_profit_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    capital_required_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    max_buy_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    max_hammer_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    all_in_acquisition_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    expected_resale_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    expected_net_resale_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    expected_days_to_sale: Mapped[int | None] = mapped_column(Integer)
    identity_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    valuation_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    condition_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    why: Mapped[str] = mapped_column(Text, nullable=False)
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    cost_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    risks: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    ignored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    purchased: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ScanJob(Base, TimestampMixin):
    __tablename__ = "scan_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(64))
    query: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    listings_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    opportunities_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class WatchlistItem(Base, TimestampMixin):
    __tablename__ = "watchlist_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(512), nullable=False)
    listing_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("listings.id"))
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Alert(Base, TimestampMixin):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opportunities.id"))
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class Purchase(Base, TimestampMixin):
    __tablename__ = "purchases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opportunities.id"))
    listing_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("listings.id"))
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    fees: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    shipping: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    refurbishment: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="purchased")


class Sale(Base, TimestampMixin):
    __tablename__ = "sales"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    purchase_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchases.id"), nullable=False, index=True)
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sale_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    fees: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    shipping: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    days_to_sale: Mapped[int | None] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Outcome(Base, TimestampMixin):
    __tablename__ = "outcomes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    purchase_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchases.id"), nullable=False)
    sale_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sales.id"))
    predicted_resale: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    actual_resale: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    predicted_profit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    actual_profit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    predicted_days: Mapped[int | None] = mapped_column(Integer)
    actual_days: Mapped[int | None] = mapped_column(Integer)
    predicted_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    actual_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    valuation_error: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    profit_error: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    days_error: Mapped[int | None] = mapped_column(Integer)
    cost_error: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    extras: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_created", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    actor: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


__all__ = [
    "AuctionLot",
    "Alert",
    "AuditEvent",
    "Comparable",
    "FxRate",
    "Listing",
    "ListingComponent",
    "Opportunity",
    "Outcome",
    "Product",
    "ProductIdentityLink",
    "Purchase",
    "RawListing",
    "Sale",
    "ScanJob",
    "Source",
    "SourceHealth",
    "TaxRule",
    "Valuation",
    "WatchlistItem",
]
