"""Owner dashboard — money first, not a generic admin theme."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.ops import get_db
from app.audit.self_audit import run_self_audit
from app.certification.engine import CATEGORY_DEFAULTS, EXIT_DEFAULTS, current_level
from app.core.config import settings
from app.inventory.service import mark_purchased, mark_sold
from app.jobs.scheduler import scheduler_status
from app.models.orm import (
    Comparable,
    InventoryItem,
    Listing,
    Opportunity,
    OwnerSale,
    PaperTrade,
    ScanJob,
    Source,
    Valuation,
)
from app.paper.service import paper_summary
from app.pipeline.service import run_scan, seed_sources
from app.pipeline.url import value_manual, value_url
from app.sold.importers import import_marketplace_export
from app.sold.owner import import_owner_sales
from app.strategies.defaults import seed_strategies

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


def _attach_listing(session: Session, opp: Opportunity) -> Opportunity:
    listing = session.get(Listing, opp.listing_id)
    opp.listing = listing  # type: ignore[attr-defined]
    return opp


def _ctx(session: Session) -> dict:
    seed_sources(session)
    seed_strategies(session)
    sources = session.scalars(select(Source).order_by(Source.id)).all()
    live = sum(1 for s in sources if s.status == "LIVE")
    owner_n = len(session.scalars(select(OwnerSale).limit(500)).all())
    paper_n = len(session.scalars(select(PaperTrade).where(PaperTrade.status != "open").limit(500)).all())
    inv = session.scalars(select(InventoryItem).limit(500)).all()
    return {
        "settings": settings,
        "sources": sources,
        "cert_level": current_level(
            live_sources=live,
            owner_sales=owner_n,
            paper_closed=paper_n,
            real_purchases=len(inv),
        ).value,
        "scheduler": scheduler_status(),
        "safe_start": settings.safe_start_mode,
    }


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    opps = session.scalars(
        select(Opportunity)
        .where(Opportunity.ignored.is_(False))
        .order_by(Opportunity.expected_profit_eur.desc())
        .limit(80)
    ).all()
    for opp in opps:
        _attach_listing(session, opp)
    jobs = session.scalars(select(ScanJob).order_by(ScanJob.created_at.desc()).limit(8)).all()
    inventory = session.scalars(select(InventoryItem).order_by(InventoryItem.purchased_at.desc()).limit(20)).all()
    buys = [o for o in opps if o.money_ready_decision == "BUY_READY"]

    def _extras(row: Opportunity) -> dict:
        listing = getattr(row, "listing", None)
        return (listing.extras or {}) if listing else {}

    near = [
        o
        for o in opps
        if o.money_ready_decision in {"WATCH", "REVIEW"}
        and (_extras(o).get("near_buy") or (o.gate_results or {}).get("failures"))
    ]
    closing = [o for o in opps if o.urgency in {"act_now", "bid_later"}]
    drops = [o for o in opps if _extras(o).get("price_drop")]
    ctx = _ctx(session)
    ctx.update(
        {
            "opportunities": opps,
            "jobs": jobs,
            "inventory": inventory,
            "buys": buys,
            "near": near,
            "watch": [o for o in opps if o.money_ready_decision == "WATCH"],
            "review": [o for o in opps if o.money_ready_decision == "REVIEW"],
            "closing": closing,
            "drops": drops,
        }
    )
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@router.post("/scan-now")
async def scan_now(session: Session = Depends(get_db)) -> RedirectResponse:
    await run_scan(session, trigger="dashboard", limit=12)
    return RedirectResponse("/", status_code=303)


@router.post("/scan-source")
async def scan_source(source_id: str = Form(...), session: Session = Depends(get_db)) -> RedirectResponse:
    await run_scan(session, source_id=source_id, trigger="dashboard-source", limit=12)
    return RedirectResponse("/", status_code=303)


@router.post("/scan-search")
async def scan_search(query: str = Form(...), session: Session = Depends(get_db)) -> RedirectResponse:
    await run_scan(session, query=query, trigger="dashboard-search", limit=12)
    return RedirectResponse("/", status_code=303)


@router.post("/scan-category")
async def scan_category(category: str = Form(...), session: Session = Depends(get_db)) -> RedirectResponse:
    await run_scan(session, query=category, trigger="dashboard-category", limit=12)
    return RedirectResponse("/", status_code=303)


@router.post("/value-url")
async def value_this_url(url: str = Form(...), session: Session = Depends(get_db)) -> RedirectResponse:
    opp = await value_url(session, url)
    return RedirectResponse(f"/opportunities/{opp.id}/view", status_code=303)


@router.post("/value-item")
async def value_this_item(
    title: str = Form(...),
    asking: str = Form(""),
    country: str = Form("IE"),
    description: str = Form(""),
    condition: str = Form(""),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    price = Decimal(asking) if asking else None
    opp = await value_manual(
        session,
        title=title,
        description=description,
        asking=price,
        country=country,
        condition=condition,
    )
    return RedirectResponse(f"/opportunities/{opp.id}/view", status_code=303)


@router.get("/inventory", response_class=HTMLResponse)
def inventory_page(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    items = session.scalars(select(InventoryItem).order_by(InventoryItem.purchased_at.desc())).all()
    ctx = _ctx(session)
    ctx["items"] = items
    ctx["capital"] = sum((i.capital_tied_eur for i in items if i.state != "sold"), Decimal("0"))
    return templates.TemplateResponse(request, "inventory.html", ctx)


@router.get("/performance", response_class=HTMLResponse)
def performance_page(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    from app.models.orm import Outcome

    outcomes = session.scalars(select(Outcome).limit(200)).all()
    ctx = _ctx(session)
    ctx["outcomes"] = outcomes
    ctx["paper"] = paper_summary(session)
    ctx["categories"] = {k: v.value for k, v in CATEGORY_DEFAULTS.items()}
    ctx["exits"] = {k: v.value for k, v in EXIT_DEFAULTS.items()}
    return templates.TemplateResponse(request, "performance.html", ctx)


@router.get("/data-quality", response_class=HTMLResponse)
def data_quality(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    listings = session.scalars(select(Listing).limit(400)).all()
    opps = session.scalars(select(Opportunity).limit(400)).all()
    ctx = _ctx(session)
    ctx["missing_price"] = sum(1 for l in listings if l.asking_price is None)
    ctx["unknown_id"] = sum(1 for l in listings if not l.brand and not l.model)
    ctx["low_val"] = sum(1 for o in opps if o.valuation_confidence < Decimal("0.45"))
    ctx["listing_count"] = len(listings)
    return templates.TemplateResponse(request, "data_quality.html", ctx)


@router.post("/import/owner-sales")
async def upload_owner_sales(file: UploadFile, session: Session = Depends(get_db)) -> RedirectResponse:
    text = (await file.read()).decode("utf-8", errors="replace")
    import_owner_sales(session, text)
    return RedirectResponse("/performance", status_code=303)


@router.post("/import/marketplace-sales")
async def upload_marketplace_sales(file: UploadFile, session: Session = Depends(get_db)) -> RedirectResponse:
    text = (await file.read()).decode("utf-8", errors="replace")
    import_marketplace_export(session, text)
    return RedirectResponse("/performance", status_code=303)


@router.post("/self-audit")
def self_audit_now(session: Session = Depends(get_db)) -> RedirectResponse:
    run_self_audit(session)
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
        {"opportunity": opp, "listing": listing, "comps": comps, "valuation": valuation, **_ctx(session)},
    )


@router.post("/opportunities/{opportunity_id}/ignore")
def dash_ignore(opportunity_id: str, session: Session = Depends(get_db)) -> RedirectResponse:
    row = session.get(Opportunity, UUID(opportunity_id))
    if row:
        row.ignored = True
        row.money_ready_decision = "IGNORE"
    return RedirectResponse("/", status_code=303)


@router.post("/opportunities/{opportunity_id}/watch")
def dash_watch(opportunity_id: str, session: Session = Depends(get_db)) -> RedirectResponse:
    from app.models.orm import WatchlistItem

    row = session.get(Opportunity, UUID(opportunity_id))
    if row:
        session.add(WatchlistItem(kind="listing", value=str(row.listing_id), listing_id=row.listing_id, product_id=row.product_id))
    return RedirectResponse("/", status_code=303)


@router.post("/opportunities/{opportunity_id}/purchase")
def purchase_now(
    opportunity_id: str,
    actual_purchase_price: str = Form(...),
    actual_shipping: str = Form("0"),
    actual_buyer_fee: str = Form("0"),
    payment_fee: str = Form("0"),
    notes: str = Form(""),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    opp = session.get(Opportunity, UUID(opportunity_id))
    if opp is None:
        return RedirectResponse("/", status_code=303)
    mark_purchased(
        session,
        opp,
        actual_purchase_price=Decimal(actual_purchase_price),
        actual_shipping=Decimal(actual_shipping or "0"),
        actual_buyer_fee=Decimal(actual_buyer_fee or "0"),
        payment_fee=Decimal(payment_fee or "0"),
        notes=notes,
    )
    return RedirectResponse("/inventory", status_code=303)


@router.post("/inventory/{item_id}/sold")
def inventory_sold(
    item_id: str,
    sale_price: str = Form(...),
    sale_channel: str = Form("ebay_ie"),
    fees: str = Form("0"),
    shipping: str = Form("0"),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    item = session.get(InventoryItem, UUID(item_id))
    if item:
        mark_sold(
            session,
            item,
            sold_date=datetime.now(timezone.utc),
            sale_price=Decimal(sale_price),
            sale_channel=sale_channel,
            fees=Decimal(fees or "0"),
            shipping=Decimal(shipping or "0"),
        )
    return RedirectResponse("/inventory", status_code=303)
