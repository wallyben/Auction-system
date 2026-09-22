"""Append-only commercial-vehicle market observations.

Revision ID: 20260922_0011
Revises: 20260901_0010
Create Date: 2026-09-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260922_0011"
down_revision: str | None = "20260901_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cv_market_observations",
        sa.Column("observation_id", sa.String(length=64), primary_key=True),
        sa.Column("listing_id", sa.String(length=128), nullable=False),
        sa.Column("model_family", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_cv_market_observations_listing_id", "cv_market_observations", ["listing_id"])
    op.create_index("ix_cv_market_observations_model_family", "cv_market_observations", ["model_family"])
    op.create_index("ix_cv_market_observations_observed_at", "cv_market_observations", ["observed_at"])


def downgrade() -> None:
    op.drop_index("ix_cv_market_observations_observed_at", table_name="cv_market_observations")
    op.drop_index("ix_cv_market_observations_model_family", table_name="cv_market_observations")
    op.drop_index("ix_cv_market_observations_listing_id", table_name="cv_market_observations")
    op.drop_table("cv_market_observations")
