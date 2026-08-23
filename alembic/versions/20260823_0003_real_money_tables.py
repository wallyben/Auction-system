"""Real-money completion tables and opportunity money-ready columns.

Revision ID: 20260823_0003
Revises: 20260823_0002
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20260823_0003"
down_revision: str | None = "20260823_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW = {
    "sold_evidence",
    "owner_sales",
    "inventory_items",
    "paper_trades",
    "scan_strategies",
    "listing_observations",
    "loss_postmortems",
    "calibration_records",
    "metric_events",
    "self_audits",
}


def upgrade() -> None:
    import app.models  # noqa: F401
    from app.db.base import Base

    bind = op.get_bind()
    tables = [table for name, table in Base.metadata.tables.items() if name in _NEW]
    Base.metadata.create_all(bind=bind, tables=tables)
    statements = [
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS engine_decision VARCHAR(16) NOT NULL DEFAULT 'REVIEW'",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS money_ready BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS money_ready_decision VARCHAR(16) NOT NULL DEFAULT 'REVIEW'",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS expected_value_eur NUMERIC(12,2) NOT NULL DEFAULT 0",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS ideal_offer_eur NUMERIC(12,2)",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS acceptable_offer_eur NUMERIC(12,2)",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS walk_away_eur NUMERIC(12,2)",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS best_exit_channel VARCHAR(64)",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS fastest_exit_channel VARCHAR(64)",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS safest_exit_channel VARCHAR(64)",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS highest_net_exit VARCHAR(64)",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS mispricing_score NUMERIC(8,4)",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS discount_to_expected NUMERIC(8,4)",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS urgency VARCHAR(32)",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS gate_results JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS exit_analysis JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS negotiation JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS provenance_pack JSONB NOT NULL DEFAULT '{}'::jsonb",
        "CREATE INDEX IF NOT EXISTS ix_opportunities_money_ready_decision ON opportunities (money_ready_decision)",
        "CREATE INDEX IF NOT EXISTS ix_opportunities_expected_profit ON opportunities (expected_profit_eur DESC)",
        "ALTER TABLE sources ADD COLUMN IF NOT EXISTS commercial_quality VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN'",
    ]
    for stmt in statements:
        bind.execute(text(stmt))


def downgrade() -> None:
    import app.models  # noqa: F401
    from app.db.base import Base

    bind = op.get_bind()
    tables = [table for name, table in Base.metadata.tables.items() if name in _NEW]
    Base.metadata.drop_all(bind=bind, tables=tables)
