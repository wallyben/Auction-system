"""Paper trades for BUY_READY candidates. Never fabricate a sale."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import Listing, Opportunity, PaperTrade


def should_open_paper(opportunity: Opportunity) -> tuple[bool, str]:
    if opportunity.money_ready:
        return True, "BUY_READY"
    if opportunity.engine_decision == "BUY" or opportunity.decision == "BUY":
        return True, "ENGINE_BUY"
    failures = (opportunity.gate_results or {}).get("failures") or []
    production_ok = "PRODUCTION_SOURCE_PASS" not in failures
    if (
        opportunity.money_ready_decision == "WATCH"
        and production_ok
        and (opportunity.expected_profit_eur or 0) > 0
    ):
        return True, "NEAR_BUY"
    return False, ""


def open_paper_trade(session: Session, opportunity: Opportunity) -> PaperTrade | None:
    ok, reason = should_open_paper(opportunity)
    if not ok:
        return None
    existing = session.scalar(select(PaperTrade).where(PaperTrade.opportunity_id == opportunity.id))
    if existing:
        return existing
    listing = session.get(Listing, opportunity.listing_id)
    trade = PaperTrade(
        opportunity_id=opportunity.id,
        listing_id=opportunity.listing_id,
        title=listing.title if listing else "Unknown",
        paper_purchase_price=opportunity.all_in_acquisition_eur,
        paper_purchase_date=datetime.now(timezone.utc),
        predicted_exit=opportunity.best_exit_channel,
        predicted_profit=opportunity.expected_profit_eur,
        predicted_days=opportunity.expected_days_to_sale,
        status="open",
        observed_outcome=None,
        notes=(
            f"Opened as {reason}. Disappearance is not a sale. "
            "Outcome unknown until observed evidence exists."
        ),
    )
    session.add(trade)
    session.flush()
    return trade


def paper_summary(session: Session) -> dict:
    rows = session.scalars(select(PaperTrade).order_by(PaperTrade.created_at.desc()).limit(200)).all()
    return {
        "count": len(rows),
        "open": sum(1 for r in rows if r.status == "open"),
        "note": "No fabricated dispositions. Open trades remain open until evidence exists.",
        "trades": [
            {
                "id": str(r.id),
                "title": r.title,
                "price": str(r.paper_purchase_price),
                "predicted_profit": str(r.predicted_profit),
                "status": r.status,
                "outcome": r.observed_outcome,
            }
            for r in rows[:20]
        ],
    }
