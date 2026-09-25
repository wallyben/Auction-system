"""Append-only commercial-vehicle market observations.

Rows are inserted. The repository does not update price or status in place.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CvMarketObservationRow(Base):
    __tablename__ = "cv_market_observations"

    observation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    listing_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    model_family: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class CvEvaluationRow(Base):
    __tablename__ = "cv_evaluations"

    evaluation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    listing_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    shadow: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)


class CvSourceStateRow(Base):
    __tablename__ = "cv_source_state"

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)


class CvAuctionRow(Base):
    __tablename__ = "cv_auctions"

    auction_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sale_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="catalogue")
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="GBP")
    fx: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)


class CvLotRow(Base):
    __tablename__ = "cv_lots"

    lot_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    auction_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    lot_number: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    registration: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    owner_status: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    owner_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    current_bid_gbp: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)


class CvOwnerEvidenceRow(Base):
    __tablename__ = "cv_owner_evidence"

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    vehicle_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
