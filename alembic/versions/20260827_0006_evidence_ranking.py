"""Evidence ranking columns and valuation algorithm version.

Revision ID: 20260827_0006
Revises: 20260825_0005
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20260827_0006"
down_revision: str | None = "20260825_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    statements = [
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS ranking_group VARCHAR(32) NOT NULL DEFAULT 'UNVALUED'",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS ranking_score NUMERIC(14,4) NOT NULL DEFAULT 0",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS algorithm_version VARCHAR(32) NOT NULL DEFAULT ''",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS evidence_as_of TIMESTAMPTZ",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS value_status VARCHAR(32) NOT NULL DEFAULT 'UNVALIDATED_VALUE'",
        "ALTER TABLE valuations ADD COLUMN IF NOT EXISTS algorithm_version VARCHAR(32) NOT NULL DEFAULT ''",
        "ALTER TABLE valuations ADD COLUMN IF NOT EXISTS evidence_as_of TIMESTAMPTZ",
        "CREATE INDEX IF NOT EXISTS ix_opportunities_ranking ON opportunities (ranking_group, ranking_score DESC)",
    ]
    for stmt in statements:
        bind.execute(text(stmt))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP INDEX IF EXISTS ix_opportunities_ranking"))
