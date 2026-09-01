"""Dedicated worker queue columns and coherent valuation book.

Revision ID: 20260901_0010
Revises: 20260829_0009
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20260901_0010"
down_revision: str | None = "20260829_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text(
            "ALTER TABLE pipeline_workers "
            "ADD COLUMN IF NOT EXISTS details JSONB NOT NULL DEFAULT '{}'::jsonb"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("ALTER TABLE pipeline_workers DROP COLUMN IF EXISTS details"))
