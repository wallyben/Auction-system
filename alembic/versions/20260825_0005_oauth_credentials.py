"""Persist OAuth refresh tokens (Render disks are ephemeral).

Revision ID: 20260825_0005
Revises: 20260823_0004
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect

revision: str = "20260825_0005"
down_revision: str | None = "20260823_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW = {"oauth_credentials"}


def upgrade() -> None:
    import app.models  # noqa: F401
    import app.models.oauth  # noqa: F401
    from app.db.base import Base

    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    tables = [table for name, table in Base.metadata.tables.items() if name in _NEW and name not in existing]
    if tables:
        Base.metadata.create_all(bind=bind, tables=tables)


def downgrade() -> None:
    import app.models.oauth  # noqa: F401
    from app.db.base import Base

    bind = op.get_bind()
    tables = [table for name, table in Base.metadata.tables.items() if name in _NEW]
    Base.metadata.drop_all(bind=bind, tables=tables)
