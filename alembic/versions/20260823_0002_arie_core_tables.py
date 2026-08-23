"""Create ARIE core tables.

Revision ID: 20260823_0002
Revises: 20260223_0001
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260823_0002"
down_revision: str | None = "20260223_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# auction_lots is created by 20260223_0001 and must not be rebuilt.
_SKIP = {"auction_lots"}


def upgrade() -> None:
    import app.models  # noqa: F401
    from app.db.base import Base

    bind = op.get_bind()
    tables = [table for name, table in Base.metadata.tables.items() if name not in _SKIP]
    Base.metadata.create_all(bind=bind, tables=tables)


def downgrade() -> None:
    import app.models  # noqa: F401
    from app.db.base import Base

    bind = op.get_bind()
    tables = [table for name, table in Base.metadata.tables.items() if name not in _SKIP]
    Base.metadata.drop_all(bind=bind, tables=tables)
