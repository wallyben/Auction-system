"""Exclusive pipeline job lease/history.

Revision ID: 20260829_0008
Revises: 20260827_0007
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20260829_0008"
down_revision: str | None = "20260827_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    statements = [
        """
        CREATE TABLE IF NOT EXISTS pipeline_jobs (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            name VARCHAR(64) NOT NULL,
            trigger VARCHAR(32) NOT NULL DEFAULT 'scheduler',
            status VARCHAR(32) NOT NULL DEFAULT 'running',
            started_at TIMESTAMPTZ,
            heartbeat_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            error TEXT,
            details JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_pipeline_jobs_status_started ON pipeline_jobs (status, started_at)",
        "CREATE INDEX IF NOT EXISTS ix_pipeline_jobs_name_started ON pipeline_jobs (name, started_at)",
        "CREATE INDEX IF NOT EXISTS ix_pipeline_jobs_name ON pipeline_jobs (name)",
        "CREATE INDEX IF NOT EXISTS ix_pipeline_jobs_status ON pipeline_jobs (status)",
        "CREATE INDEX IF NOT EXISTS ix_pipeline_jobs_expires_at ON pipeline_jobs (expires_at)",
    ]
    for stmt in statements:
        bind.execute(text(stmt))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS pipeline_jobs"))
