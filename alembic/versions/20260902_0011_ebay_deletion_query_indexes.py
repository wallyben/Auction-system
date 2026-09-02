"""Indexes for query-driven eBay account-deletion.

Revision ID: 20260902_0011
Revises: 20260901_0010
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect, text

revision: str = "20260902_0011"
down_revision: str | None = "20260901_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = (
    ("ix_comparables_source_id", "comparables", ["source_id"]),
    ("ix_watchlist_items_kind_value", "watchlist_items", ["kind", "value"]),
    ("ix_watchlist_items_listing_id", "watchlist_items", ["listing_id"]),
    ("ix_alerts_opportunity_id", "alerts", ["opportunity_id"]),
    ("ix_purchases_listing_id", "purchases", ["listing_id"]),
    ("ix_inventory_items_listing_id", "inventory_items", ["listing_id"]),
    ("ix_paper_trades_listing_id", "paper_trades", ["listing_id"]),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing: set[str] = set()
    for table in inspector.get_table_names():
        for index in inspector.get_indexes(table):
            name = index.get("name")
            if name:
                existing.add(name)
    for name, table, cols in _INDEXES:
        if name in existing:
            continue
        op.create_index(name, table, cols)
    if bind.dialect.name == "postgresql":
        bind.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_listings_extras_seller_username_hash "
                "ON listings ((extras->>'seller_username_hash')) "
                "WHERE source_id = 'ebay_browse'"
            )
        )
        bind.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_listings_extras_seller_user_id_hash "
                "ON listings ((extras->>'seller_user_id_hash')) "
                "WHERE source_id = 'ebay_browse'"
            )
        )
        bind.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_listings_extras_seller_eias_hash "
                "ON listings ((extras->>'seller_eias_hash')) "
                "WHERE source_id = 'ebay_browse'"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(text("DROP INDEX IF EXISTS ix_listings_extras_seller_username_hash"))
        bind.execute(text("DROP INDEX IF EXISTS ix_listings_extras_seller_user_id_hash"))
        bind.execute(text("DROP INDEX IF EXISTS ix_listings_extras_seller_eias_hash"))
    for name, table, _cols in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
