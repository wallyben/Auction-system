"""Owner dashboard — Irish reseller floor, not a generic admin theme."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.ops import get_db
from app.core.config import settings
from app.models.orm import Comparable, Listing, Opportunity, ScanJob, Source, Valuation
from app.pipeline.service import run_scan, seed_sources

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


def _attach_listing(session: Session, opp: Opportunity) -> Opportunity:
    listing = session.get(Listing, opp.listing_id)
    opp.listing = listing  # type: ignore[attr-defined]
    return opp


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    seed_sources(session)
    opps = session.scalars(
        select(Opportunity)
        .where(Opportunity.ignored.is_(False))
        .order_by(Opportunity.score.desc())
        .limit(50)
    ).all()
    for opp in opps:
        _attach_listing(session, opp)
    sources = session.scalars(select(Source).order_by(Source.id)).all()
    jobs = session.scalars(select(ScanJob).order_by(ScanJob.created_at.desc()).limit(8)).all()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "opportunities": opps,
            "sources": sources,
            "jobs": jobs,
            "settings": settings,
            "buys": sum(1 for opp in opps if opp.decision == "BUY"),
            "watch": sum(1 for opp in opps if opp.decision == "WATCH"),
            "review": sum(1 for opp in opps if opp.decision == "REVIEW"),
        },
    )


@router.post("/scan-now")
async def scan_now(session: Session = Depends(get_db)) -> RedirectResponse:
    await run_scan(session, trigger="dashboard", limit=12)
    return RedirectResponse("/", status_code=303)


@router.get("/opportunities/{opportunity_id}/view", response_class=HTMLResponse)
def opportunity_view(
    opportunity_id: str, request: Request, session: Session = Depends(get_db)
) -> HTMLResponse:
    opp = session.get(Opportunity, UUID(opportunity_id))
    listing = session.get(Listing, opp.listing_id) if opp else None
    if opp:
        opp.listing = listing  # type: ignore[attr-defined]
    comps = []
    valuation = None
    if listing:
        comps = session.scalars(
            select(Comparable)
            .where(Comparable.subject_listing_id == listing.id)
            .order_by(Comparable.created_at.desc())
            .limit(40)
        ).all()
        valuation = session.scalar(
            select(Valuation)
            .where(Valuation.listing_id == listing.id)
            .order_by(Valuation.created_at.desc())
            .limit(1)
        )
    return templates.TemplateResponse(
        request,
        "opportunity.html",
        {"opportunity": opp, "listing": listing, "comps": comps, "valuation": valuation},
    )
