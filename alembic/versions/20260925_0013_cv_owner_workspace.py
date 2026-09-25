"""Persisted owner auctions and lots.

Revision ID: 20260925_0013
Revises: 20260923_0012
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260925_0013"
down_revision: str | None = "20260923_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    names = set(sa.inspect(op.get_bind()).get_table_names())
    if "cv_auctions" not in names:
        op.create_table(
            "cv_auctions",
            sa.Column("auction_id", sa.String(length=64), primary_key=True),
            sa.Column("sale_code", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=256), nullable=False),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("currency", sa.String(length=8), nullable=False),
            sa.Column("fx", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        )
        op.create_index("ix_cv_auctions_sale_code", "cv_auctions", ["sale_code"])
    if "cv_lots" not in names:
        op.create_table(
            "cv_lots",
            sa.Column("lot_id", sa.String(length=80), primary_key=True),
            sa.Column("auction_id", sa.String(length=64), nullable=False),
            sa.Column("lot_number", sa.String(length=16), nullable=False),
            sa.Column("title", sa.String(length=512), nullable=False),
            sa.Column("registration", sa.String(length=32), nullable=False),
            sa.Column("owner_status", sa.String(length=40), nullable=False),
            sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("owner_note", sa.Text(), nullable=False, server_default=""),
            sa.Column("current_bid_gbp", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        )
        op.create_index("ix_cv_lots_auction_id", "cv_lots", ["auction_id"])


def downgrade() -> None:
    op.drop_index("ix_cv_lots_auction_id", table_name="cv_lots")
    op.drop_table("cv_lots")
    op.drop_index("ix_cv_auctions_sale_code", table_name="cv_auctions")
    op.drop_table("cv_auctions")
