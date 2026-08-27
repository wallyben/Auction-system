"""Evidence ranking columns and CompSniper sold-query cache.

Revision ID: 20260827_0007
Revises: 20260827_0006
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20260827_0007"
down_revision: str | None = "20260827_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    statements = [
        """
        CREATE TABLE IF NOT EXISTS sold_query_cache (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            cache_key VARCHAR(64) NOT NULL,
            canonical_product_id VARCHAR(512) NOT NULL,
            variant VARCHAR(64) NOT NULL DEFAULT 'body',
            marketplace VARCHAR(8) NOT NULL DEFAULT 'GB',
            condition_bucket VARCHAR(32) NOT NULL DEFAULT 'used',
            keyword VARCHAR(1024) NOT NULL DEFAULT '',
            queried_at TIMESTAMPTZ NOT NULL,
            raw_count INTEGER NOT NULL DEFAULT 0,
            accepted_count INTEGER NOT NULL DEFAULT 0,
            rejected_count INTEGER NOT NULL DEFAULT 0,
            last_http_status INTEGER,
            quota_remaining INTEGER,
            ttl_hours INTEGER NOT NULL DEFAULT 24,
            extras JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_sold_query_cache_key ON sold_query_cache (cache_key)",
        "CREATE INDEX IF NOT EXISTS ix_sold_query_cache_product ON sold_query_cache (canonical_product_id)",
    ]
    for stmt in statements:
        bind.execute(text(stmt))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS sold_query_cache"))
