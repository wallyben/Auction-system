"""Append-only commercial-van operational tables.

Revision ID: 20260923_0012
Revises: 20260922_0011
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260923_0012"
down_revision: str | None = "20260922_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cv_evaluations",
        sa.Column("evaluation_id", sa.String(length=64), primary_key=True),
        sa.Column("listing_key", sa.String(length=160), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("shadow", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.create_index("ix_cv_evaluations_listing_key", "cv_evaluations", ["listing_key"])
    op.create_index("ix_cv_evaluations_evaluated_at", "cv_evaluations", ["evaluated_at"])
    op.create_table(
        "cv_source_state",
        sa.Column("source_id", sa.String(length=64), primary_key=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.create_table(
        "cv_owner_evidence",
        sa.Column("evidence_id", sa.String(length=64), primary_key=True),
        sa.Column("vehicle_key", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.create_index("ix_cv_owner_evidence_vehicle_key", "cv_owner_evidence", ["vehicle_key"])


def downgrade() -> None:
    op.drop_index("ix_cv_owner_evidence_vehicle_key", table_name="cv_owner_evidence")
    op.drop_table("cv_owner_evidence")
    op.drop_table("cv_source_state")
    op.drop_index("ix_cv_evaluations_evaluated_at", table_name="cv_evaluations")
    op.drop_index("ix_cv_evaluations_listing_key", table_name="cv_evaluations")
    op.drop_table("cv_evaluations")
