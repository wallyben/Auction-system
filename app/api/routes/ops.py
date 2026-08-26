"""HTTP API for health, scans, opportunities, and owner actions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db_session, get_session_factory, probe_database
from app.db.url import classify_db_error
from app.jobs.scheduler import scheduler_status
from app.models.orm import Listing, Opportunity, Purchase, ScanJob, Source, WatchlistItem
from app.pipeline.service import evaluate_listing, persist_listing, record_health, refresh_fx, run_scan, seed_sources
from app.pipeline.service import _comps_for
from app.privacy.ebay_health import notification_health
from app.sources.manual import CsvImportAdapter

router = APIRouter()


def get_db() -> Any:
    yield from get_db_session()


class ScanRequest(BaseModel):
    source_id: str | None = None
    query: str | None = None
    limit: int = Field(default=12, ge=1, le=80)


class OutcomeRequest(BaseModel):
    opportunity_id: str
    purchase_price_eur: Decimal
    extra_fees_eur: Decimal = Decimal("0")
    notes: str = ""


@router.get("/health")
@router.head("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/db")
def health_db() -> JSONResponse:
    """Real database probe. 200 only when connection and a schema query succeed."""
    result = probe_database()
    if result["ok"]:
        return JSONResponse({"status": "ok", "database": "up"}, status_code=200)
    body = {
        "status": "error",
        "database": "down",
        "reason": result["reason"],
        "configured": result["configured"],
        "scheme": result["scheme"],
        "sqlalchemy_scheme": result["sqlalchemy_scheme"],
        "host_present": result["host_present"],
        "database_present": result["database_present"],
    }
    return JSONResponse(body, status_code=503)


@router.get("/health/sources")
def health_sources(session: Session = Depends(get_db)) -> dict[str, Any]:
    seed_sources(session)
    rows = session.scalars(select(Source).order_by(Source.id)).all()
    return {
        "status": "ok",
        "sources": [
            {
                "id": row.id,
                "name": row.display_name,
                "status": row.status,
                "reason": row.status_reason,
                "last_success_at": row.last_success_at.isoformat() if row.last_success_at else None,
                "last_error": row.last_error,
                "enabled": row.enabled,
            }
            for row in rows
        ],
    }


@router.get("/health/workers")
def health_workers() -> dict[str, Any]:
    return {"status": "ok", **scheduler_status()}


@router.get("/health/ebay-notifications")
def health_ebay_notifications() -> dict[str, Any]:
    """Local readiness for the deletion webhook. Does not claim eBay subscription.

    GET challenge verification does not need the database. A down database is
    reported honestly and does not 500 this probe.
    """
    try:
        session = get_session_factory()()
    except Exception as exc:  # noqa: BLE001 — never leak the connection URL
        payload = notification_health(None)
        payload["database"] = "down"
        payload["processor"] = "database_unavailable"
        payload["ready"] = False
        payload["database_reason"] = classify_db_error(exc)
        return payload
    try:
        return notification_health(session)
    finally:
        session.close()


@router.post("/scans")
async def create_scan(payload: ScanRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    job = await run_scan(
        session,
        source_id=payload.source_id,
        query=payload.query,
        trigger="api",
        limit=payload.limit,
    )
    return {
        "id": str(job.id),
        "status": job.status,
        "listings_seen": job.listings_seen,
        "opportunities_written": job.opportunities_written,
        "error": job.error,
        "details": job.details,
    }


@router.get("/scans")
def list_scans(session: Session = Depends(get_db)) -> dict[str, Any]:
    rows = session.scalars(select(ScanJob).order_by(ScanJob.created_at.desc()).limit(20)).all()
    return {
        "scans": [
            {
                "id": str(row.id),
                "status": row.status,
                "trigger": row.trigger,
                "source_id": row.source_id,
                "query": row.query,
                "listings_seen": row.listings_seen,
                "opportunities_written": row.opportunities_written,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "error": row.error,
            }
            for row in rows
        ]
    }


@router.get("/listings")
def list_listings(limit: int = 500, session: Session = Depends(get_db)) -> dict[str, Any]:
    rows = session.scalars(select(Listing).order_by(Listing.last_seen_at.desc()).limit(min(max(limit, 1), 1000))).all()
    return {
        "count": len(rows),
        "listings": [
            {
                "id": str(row.id),
                "source_id": row.source_id,
                "external_id": row.external_id,
                "title": row.title,
                "url": row.url,
                "asking_price": str(row.asking_price) if row.asking_price is not None else None,
                "currency": row.currency,
                "country": row.country,
                "condition_raw": row.condition_raw,
                "condition_grade": row.condition_grade,
                "category": row.category,
                "brand": row.brand,
                "model": row.model,
                "variant": row.variant,
                "extras": {
                    "marketplace": (row.extras or {}).get("marketplace"),
                    "conditionId": (row.extras or {}).get("conditionId"),
                    "sandbox": (row.extras or {}).get("sandbox"),
                },
            }
            for row in rows
        ],
    }


@router.get("/opportunities")
def list_opportunities(decision: str | None = None, session: Session = Depends(get_db)) -> dict[str, Any]:
    stmt = select(Opportunity).order_by(Opportunity.score.desc())
    if decision:
        stmt = stmt.where(Opportunity.decision == decision.upper())
    rows = session.scalars(stmt.limit(250)).all()
    return {"opportunities": [_summary(session, row) for row in rows]}


@router.get("/opportunities/{opportunity_id}")
def get_opportunity(opportunity_id: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    row = session.get(Opportunity, uuid.UUID(opportunity_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return _detail(session, row)


@router.post("/opportunities/{opportunity_id}/ignore")
def ignore_opportunity(opportunity_id: str, session: Session = Depends(get_db)) -> dict[str, str]:
    row = session.get(Opportunity, uuid.UUID(opportunity_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    row.ignored = True
    row.decision = "IGNORE"
    return {"status": "ignored"}


@router.post("/opportunities/{opportunity_id}/watch")
def watch_opportunity(opportunity_id: str, session: Session = Depends(get_db)) -> dict[str, str]:
    row = session.get(Opportunity, uuid.UUID(opportunity_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    listing = session.get(Listing, row.listing_id)
    session.add(
        WatchlistItem(
            kind="listing",
            value=str(row.listing_id),
            listing_id=row.listing_id,
            product_id=row.product_id,
            notes=listing.title if listing else "",
        )
    )
    return {"status": "watching"}


@router.post("/purchases")
def record_purchase(payload: OutcomeRequest, session: Session = Depends(get_db)) -> dict[str, str]:
    opp = session.get(Opportunity, uuid.UUID(payload.opportunity_id))
    if opp is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    opp.purchased = True
    session.add(
        Purchase(
            opportunity_id=opp.id,
            listing_id=opp.listing_id,
            purchased_at=datetime.now(timezone.utc),
            purchase_price=payload.purchase_price_eur,
            fees=payload.extra_fees_eur,
            notes=payload.notes,
        )
    )
    return {"status": "recorded"}


@router.post("/import/csv")
async def import_csv(file: UploadFile = File(...), session: Session = Depends(get_db)) -> dict[str, Any]:
    text = (await file.read()).decode("utf-8", errors="replace")
    items = CsvImportAdapter().parse(text)
    rates = await refresh_fx(session)
    written = 0
    for item in items:
        listing = persist_listing(session, item)
        comps = await _comps_for(listing, rates)
        evaluate_listing(session, listing, comps, rates)
        written += 1
    return {"imported": written}


@router.get("/config")
def read_config() -> dict[str, Any]:
    from app.sold.token_store import token_status

    oauth: dict[str, Any] = {}
    try:
        session = get_session_factory()()
        try:
            oauth = token_status(session)
        finally:
            session.close()
    except Exception:
        oauth = token_status(None)
    return {
        "home_country": settings.home_country,
        "base_currency": settings.base_currency,
        "min_profit_eur": settings.min_profit_eur,
        "min_roi": settings.min_roi,
        "min_confidence": settings.min_confidence,
        "max_capital_per_item_eur": settings.max_capital_per_item_eur,
        "max_days_to_sale": settings.max_days_to_sale,
        "enabled_sources": settings.source_ids(),
        "scan_queries": settings.query_list(),
        "ebay_configured": bool(settings.ebay_client_id and settings.ebay_client_secret),
        "sandbox_used": settings.ebay_api_env == "sandbox",
        "safe_start_mode": settings.safe_start_mode,
        "owner_oauth_connected": oauth.get("owner_oauth_connected"),
        "scope_valid": oauth.get("scope_valid"),
        "last_refresh_at": oauth.get("last_refresh_at"),
        "last_sold_ingest_at": oauth.get("last_sold_ingest_at"),
        "last_ingest_count": oauth.get("last_ingest_count"),
        "secrets_included": False,
    }


def _summary(session: Session, row: Opportunity) -> dict[str, Any]:
    listing = session.get(Listing, row.listing_id)
    return {
        "id": str(row.id),
        "decision": row.decision,
        "score": str(row.score),
        "title": listing.title if listing else "",
        "source": listing.source_id if listing else "",
        "url": listing.url if listing else "",
        "asking_price": str(listing.asking_price) if listing and listing.asking_price is not None else None,
        "currency": listing.currency if listing else "EUR",
        "country": listing.country if listing else "",
        "expected_profit_eur": str(row.expected_profit_eur),
        "expected_roi": str(row.expected_roi),
        "max_buy_eur": str(row.max_buy_eur),
        "expected_resale_eur": str(row.expected_resale_eur),
        "expected_days_to_sale": row.expected_days_to_sale,
        "valuation_confidence": str(row.valuation_confidence),
        "identity_confidence": str(row.identity_confidence),
        "why": row.why,
        "ignored": row.ignored,
        "money_ready_decision": row.money_ready_decision,
        "engine_decision": row.engine_decision or row.decision,
        "ideal_offer_eur": str(row.ideal_offer_eur) if row.ideal_offer_eur is not None else None,
        "best_exit_channel": row.best_exit_channel,
        "downside_profit_eur": str(row.downside_profit_eur) if row.downside_profit_eur is not None else None,
        "failed_gates": (row.gate_results or {}).get("failures") or [],
    }


def _detail(session: Session, row: Opportunity) -> dict[str, Any]:
    summary = _summary(session, row)
    listing = session.get(Listing, row.listing_id)
    summary.update(
        {
            "images": listing.images if listing else [],
            "description": listing.description if listing else "",
            "brand": listing.brand if listing else None,
            "model": listing.model if listing else None,
            "condition_grade": listing.condition_grade if listing else None,
            "all_in_acquisition_eur": str(row.all_in_acquisition_eur),
            "expected_net_resale_eur": str(row.expected_net_resale_eur),
            "downside_profit_eur": str(row.downside_profit_eur),
            "upside_profit_eur": str(row.upside_profit_eur),
            "cost_breakdown": row.cost_breakdown,
            "score_breakdown": row.score_breakdown,
            "risks": row.risks,
            "last_evaluated_at": row.last_evaluated_at.isoformat(),
        }
    )
    return summary
