"""Paper trades for BUY_READY candidates. Never fabricate a sale."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import Listing, Opportunity, PaperTrade


def open_paper_trade(session: Session, opportunity: Opportunity) -> PaperTrade | None:
    if not opportunity.money_ready:
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
        notes="Opened because money_ready BUY_READY. Outcome unknown until observed.",
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
