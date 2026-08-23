"""eBay Marketplace Account Deletion tables and wider source status column.

Revision ID: 20260823_0004
Revises: 20260823_0003
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect, text

revision: str = "20260823_0004"
down_revision: str | None = "20260823_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW = {"ebay_deletion_notifications", "ebay_deletion_dead_letters"}


def upgrade() -> None:
    import app.models  # noqa: F401
    from app.db.base import Base

    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    tables = [table for name, table in Base.metadata.tables.items() if name in _NEW and name not in existing]
    if tables:
        Base.metadata.create_all(bind=bind, tables=tables)
    bind.execute(text("ALTER TABLE sources ALTER COLUMN status TYPE VARCHAR(64)"))
    bind.execute(text("ALTER TABLE source_health ALTER COLUMN status TYPE VARCHAR(64)"))


def downgrade() -> None:
    import app.models  # noqa: F401
    from app.db.base import Base

    bind = op.get_bind()
    tables = [table for name, table in Base.metadata.tables.items() if name in _NEW]
    Base.metadata.drop_all(bind=bind, tables=tables)
