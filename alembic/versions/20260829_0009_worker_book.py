"""Dedicated worker queue columns and coherent valuation book.

Revision ID: 20260829_0009
Revises: 20260829_0008
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20260829_0009"
down_revision: str | None = "20260829_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    statements = [
        "ALTER TABLE pipeline_jobs ADD COLUMN IF NOT EXISTS claimed_by VARCHAR(64)",
        "CREATE INDEX IF NOT EXISTS ix_pipeline_jobs_claimed_by ON pipeline_jobs (claimed_by)",
        "ALTER TABLE pipeline_jobs ALTER COLUMN status SET DEFAULT 'queued'",
        """
        CREATE TABLE IF NOT EXISTS book_generations (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            algorithm_version VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'building',
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            listings_total INTEGER NOT NULL DEFAULT 0,
            listings_done INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            details JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_book_generations_status ON book_generations (status)",
        """
        CREATE TABLE IF NOT EXISTS pipeline_workers (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            worker_id VARCHAR(64) NOT NULL UNIQUE,
            hostname VARCHAR(256) NOT NULL DEFAULT '',
            pid INTEGER NOT NULL DEFAULT 0,
            heartbeat_at TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ NOT NULL
        )
        """,
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS valuation_run_id UUID",
        "CREATE INDEX IF NOT EXISTS ix_opportunities_valuation_run_id ON opportunities (valuation_run_id)",
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_opportunities_valuation_run'
            ) THEN
                ALTER TABLE opportunities
                    ADD CONSTRAINT fk_opportunities_valuation_run
                    FOREIGN KEY (valuation_run_id) REFERENCES book_generations(id);
            END IF;
        END $$;
        """,
    ]
    for stmt in statements:
        bind.execute(text(stmt))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("ALTER TABLE opportunities DROP CONSTRAINT IF EXISTS fk_opportunities_valuation_run"))
    bind.execute(text("ALTER TABLE opportunities DROP COLUMN IF EXISTS valuation_run_id"))
    bind.execute(text("DROP TABLE IF EXISTS pipeline_workers"))
    bind.execute(text("DROP TABLE IF EXISTS book_generations"))
    bind.execute(text("ALTER TABLE pipeline_jobs DROP COLUMN IF EXISTS claimed_by"))
