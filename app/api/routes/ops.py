"""HTTP API for health, scans, opportunities, and owner actions."""

from __future__ import annotations

import os
import time
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
from app.core.process import process_role
from app.core.runtime import process_runtime_snapshot
from app.db.session import get_db_session, get_session_factory, probe_database
from app.db.url import classify_db_error
from app.jobs.lease import dispatch_http
from app.jobs.queue import lease_status, recent_jobs
from app.jobs.scheduler import REQUIRED_JOB_IDS, scheduler_status
from app.models.orm import Listing, Opportunity, Purchase, ScanJob, Source, WatchlistItem
from app.pipeline.service import evaluate_listing, persist_listing, record_health, refresh_fx, seed_sources
from app.pipeline.service import _comps_for
from app.privacy.ebay_health import notification_health
from app.sources.manual import CsvImportAdapter
from app.valuation.version import VALUATION_ALGORITHM_VERSION

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


def _runtime_sha() -> str:
    for key in ("RENDER_GIT_COMMIT", "SOURCE_VERSION", "GIT_COMMIT"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value[:40]
    return "unknown"


# Process birth. Distinguishes a wedged origin (same pid/uptime) from a restart.
_PROCESS_STARTED = datetime.now(timezone.utc)
_PROCESS_STARTED_MONO = time.monotonic()


@router.get("/health")
@router.head("/health")
async def health() -> dict[str, object]:
    """Liveness only. Must stay DB-free and async.

    Async so this cannot queue behind sync SQLAlchemy handlers on the default
    threadpool. Extra fields exist to tell restart vs hang on the next origin
    black hole. They do not prove the 2026-09-01 11-minute outage is fixed.
    """
    return {
        "status": "ok",
        "valuation_algorithm": VALUATION_ALGORITHM_VERSION,
        "git_sha": _runtime_sha(),
        "pid": os.getpid(),
        "started_at": _PROCESS_STARTED.isoformat(),
        "uptime_s": int(time.monotonic() - _PROCESS_STARTED_MONO),
        "process_role": process_role(),
    }


@router.get("/health/runtime")
async def health_runtime() -> dict[str, object]:
    """Process RSS/CPU/threads. Separate from liveness so /health stays tiny."""
    return {
        "status": "ok",
        "started_at": _PROCESS_STARTED.isoformat(),
        "uptime_s": int(time.monotonic() - _PROCESS_STARTED_MONO),
        "git_sha": _runtime_sha(),
        "valuation_algorithm": VALUATION_ALGORITHM_VERSION,
        **process_runtime_snapshot(),
    }


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
                "marketplace_insights": (row.config or {}).get("marketplace_insights") if row.id == "ebay_browse" else None,
            }
            for row in rows
        ],
    }


@router.get("/health/evidence")
def health_evidence(session: Session = Depends(get_db)) -> dict[str, Any]:
    """Source/evidence counters. A sold provider returning zero unexpectedly is a warning.

    Sync handler on purpose: this path is SQLAlchemy + COUNT queries. An async
    def would run those queries on the event loop and pin /health.
    """
    from sqlalchemy import func

    from app.evidence.providers.compsniper import compsniper_health
    from app.models.orm import MetricEvent, SoldEvidence, SoldQueryCache
    from app.sold.cache import cache_stats
    from app.sold.provider import sold_provider_health_sync

    names = [
        "listings_scanned",
        "exact_products",
        "evidence_queries",
        "realised_hits",
        "valuations_generated",
        "opportunities_rejected",
        "BUY_READY_count",
        "sold_provider_zero",
        "full_book_revalue",
        "compsniper_requests",
        "sold_cache_hit",
        "sold_rejected",
    ]
    counts: dict[str, float] = {}
    for name in names:
        total = session.scalar(select(func.coalesce(func.sum(MetricEvent.value), 0)).where(MetricEvent.name == name))
        counts[name] = float(total or 0)
    realised_n = session.scalar(select(func.count()).select_from(SoldEvidence)) or 0
    rejected_n = session.scalar(
        select(func.count()).select_from(SoldEvidence).where(SoldEvidence.evidence_quality == "rejected")
    ) or 0
    accepted_n = int(realised_n) - int(rejected_n)
    from app.sold.cameras import CAMERA_BODIES

    camera_ids = [body.canonical_id for body in CAMERA_BODIES]
    camera_n = 0
    if camera_ids:
        camera_n = session.scalar(
            select(func.count())
            .select_from(SoldEvidence)
            .where(
                SoldEvidence.canonical_product_id.in_(camera_ids),
                SoldEvidence.evidence_quality != "rejected",
            )
        ) or 0
    buy_ready_n = session.scalar(
        select(func.count()).select_from(Opportunity).where(Opportunity.money_ready_decision == "BUY_READY")
    ) or 0
    warning = None
    if counts.get("evidence_queries", 0) > 0 and counts.get("realised_hits", 0) == 0:
        warning = "Sold provider returned zero realised hits after evidence queries."
    cs = compsniper_health()
    cache: dict[str, object] = {"entries": 0, "fresh": 0, "stale": 0, "products": 0, "accepted_total": 0}
    last_refresh = None
    try:
        cache = cache_stats(session)
        latest = session.scalars(select(SoldQueryCache).order_by(SoldQueryCache.queried_at.desc()).limit(1)).first()
        last_refresh = latest.queried_at.isoformat() if latest and latest.queried_at else None
    except Exception:
        pass
    hits = counts.get("sold_cache_hit", 0)
    misses = counts.get("compsniper_requests", 0)
    hit_pct = round(100.0 * hits / (hits + misses), 1) if (hits + misses) else None
    providers = sold_provider_health_sync(session)
    return {
        "status": "ok",
        "metrics": counts,
        "realised_evidence_rows": int(realised_n),
        "valid_camera_sold_records": int(camera_n),
        "rejected_records": int(rejected_n),
        "accepted_sold_records": int(accepted_n),
        "query_cache": cache,
        "query_cache_hit_rate": hit_pct,
        "last_refresh": last_refresh,
        "BUY_READY": int(buy_ready_n),
        "warning": warning,
        "providers": providers,
        "compsniper": cs,
        "provider_quota": cs.get("quota_remaining"),
    }


@router.get("/paper")
def paper_trades(session: Session = Depends(get_db)) -> dict[str, Any]:
    from app.paper.service import paper_summary

    return paper_summary(session)


@router.get("/health/insights")
async def health_insights() -> dict[str, Any]:
    """One official Marketplace Insights entitlement probe. Never logs tokens."""
    from app.sold.insights import EbayMarketplaceInsightsProvider, INSIGHTS_URL, PROBE_CATEGORY_ID
    from app.sources.ebay import EbayBrowseAdapter

    adapter = EbayBrowseAdapter()
    token = None
    auth_note = None
    if adapter._missing_credentials():
        auth_note = "No eBay client credentials in this process."
    else:
        oauth = await adapter._oauth_probe()
        if oauth.get("ok"):
            token = adapter._token
        else:
            auth_note = "Browse client-credentials grant failed. Insights not probed with a token."
    provider = EbayMarketplaceInsightsProvider(token)
    result = await provider.probe(token)
    result["endpoint"] = INSIGHTS_URL[settings.ebay_api_env]
    result["marketplace"] = settings.ebay_marketplace_list()[0]
    result["category"] = PROBE_CATEGORY_ID
    if auth_note and not result.get("http_status"):
        result["entitlement_result"] = result.get("entitlement_result") or "AUTH_ERROR"
        result["response_classification"] = result.get("entitlement_result") or "AUTH_ERROR"
        result["EBAY_MARKETPLACE_INSIGHTS"] = "BLOCKED_EXTERNAL_ACCESS"
        result["note"] = auth_note
    result["secrets_included"] = False
    return result


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
async def create_scan(payload: ScanRequest) -> JSONResponse:
    result = await dispatch_http(
        "scan",
        "api",
        {"source_id": payload.source_id, "query": payload.query, "limit": payload.limit},
    )
    code = int(result.pop("http_status", 202))
    return JSONResponse(result, status_code=code)


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
    from app.opportunity.book import current_generation
    from app.opportunity.ranking import GROUP_ORDER

    generation = current_generation(session)
    stmt = select(Opportunity).where(Opportunity.algorithm_version == VALUATION_ALGORITHM_VERSION)
    if generation is not None:
        stmt = stmt.where(Opportunity.valuation_run_id == generation.id)
    if decision:
        stmt = stmt.where(Opportunity.decision == decision.upper())
    rows = list(session.scalars(stmt.limit(2000)).all())
    rows = sorted(
        rows,
        key=lambda o: (
            GROUP_ORDER.get(getattr(o, "ranking_group", None) or "UNVALUED", 9),
            -(float(getattr(o, "ranking_score", 0) or 0)),
        ),
    )[:250]
    listings_by_id: dict[Any, Listing] = {}
    listing_ids = [row.listing_id for row in rows]
    if listing_ids:
        for listing in session.scalars(select(Listing).where(Listing.id.in_(listing_ids))).all():
            listings_by_id[listing.id] = listing
    return {
        "opportunities": [_summary(session, row, listings_by_id.get(row.listing_id)) for row in rows],
        "book": {
            "algorithm_version": VALUATION_ALGORITHM_VERSION,
            "generation_id": str(generation.id) if generation else None,
            "generation_status": generation.status if generation else None,
        },
    }


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
    from app.sold.certify import live_camera_body_certification
    from app.jobs.lease import maybe_yield

    live_cert = live_camera_body_certification(session)
    written = 0
    for item in items:
        listing = persist_listing(session, item)
        comps = await _comps_for(listing, rates, session)
        evaluate_listing(session, listing, comps, rates, live_cert=live_cert, generation=current_generation(session))
        written += 1
        await maybe_yield(written, every=4)
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


def _summary(session: Session, row: Opportunity, listing: Listing | None = None) -> dict[str, Any]:
    listing = listing if listing is not None else session.get(Listing, row.listing_id)
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
        "ranking_group": getattr(row, "ranking_group", None),
        "ranking_score": str(getattr(row, "ranking_score", "") or ""),
        "value_status": getattr(row, "value_status", None),
        "algorithm_version": getattr(row, "algorithm_version", None),
        "evaluated_at": row.last_evaluated_at.isoformat() if row.last_evaluated_at else None,
        "evidence_as_of": row.evidence_as_of.isoformat() if getattr(row, "evidence_as_of", None) else None,
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
            "algorithm_version": getattr(row, "algorithm_version", None),
            "evidence_as_of": row.evidence_as_of.isoformat() if getattr(row, "evidence_as_of", None) else None,
            "value_status": getattr(row, "value_status", None),
            "ranking_group": getattr(row, "ranking_group", None),
            "provenance_pack": row.provenance_pack,
            "gate_results": row.gate_results,
        }
    )
    return summary


@router.get("/health/jobs")
def health_jobs() -> dict[str, Any]:
    status = scheduler_status()
    ids = {job.get("id") for job in status.get("jobs") or []}
    required = set(REQUIRED_JOB_IDS)
    recent: list[dict[str, object]] = []
    try:
        session = get_session_factory()()
        try:
            recent = recent_jobs(session)
        finally:
            session.close()
    except Exception:
        recent = []
    worker = (status.get("pipeline") or {}).get("worker") if isinstance(status.get("pipeline"), dict) else None
    worker_connected = bool(isinstance(worker, dict) and worker.get("connected"))
    web_scheduler = bool(status.get("web_scheduler_running"))
    return {
        **status,
        "recent_pipeline_jobs": recent,
        "required_jobs": sorted(required),
        "missing_jobs": sorted(required - ids),
        "worker_connected": worker_connected,
        "ok": required.issubset(ids)
        and bool(status.get("scheduler_running"))
        and not web_scheduler,
    }


@router.post("/ops/sold-refresh")
async def ops_sold_refresh(
    force: bool = False,
    markets: str = "GB",
    limit: int = 12,
    product: str | None = None,
) -> JSONResponse:
    """Quota-efficient CompSniper ingest: one query per canonical camera × marketplace."""
    from app.sold.cameras import camera_by_id

    if product and camera_by_id(product) is None:
        raise HTTPException(status_code=404, detail=f"Unknown camera product {product}")
    result = await dispatch_http(
        "sold-refresh",
        "api",
        {"force": force, "markets": markets, "limit": limit, "product": product, "revalidate": True},
    )
    code = int(result.pop("http_status", 202))
    return JSONResponse(result, status_code=code)


@router.post("/ops/sold-revalidate")
async def ops_sold_revalidate() -> JSONResponse:
    """Re-run identity matching on stored CompSniper tickets. Zero quota."""
    result = await dispatch_http("sold-revalidate", "api", {})
    code = int(result.pop("http_status", 202))
    return JSONResponse(result, status_code=code)


@router.post("/ops/revalue")
async def ops_revalue() -> JSONResponse:
    result = await dispatch_http(
        "revalue",
        "api",
        {"reason": f"ops:{VALUATION_ALGORITHM_VERSION}"},
    )
    code = int(result.pop("http_status", 202))
    return JSONResponse(result, status_code=code)


@router.get("/ops/jobs")
def ops_jobs(session: Session = Depends(get_db)) -> dict[str, Any]:
    return {"pipeline": lease_status(session), "jobs": recent_jobs(session, limit=20)}


@router.get("/ops/sold-quality")
def ops_sold_quality(session: Session = Depends(get_db)) -> dict[str, Any]:
    from app.sold.quality import sold_quality_report

    return sold_quality_report(session)


@router.get("/ops/certify-cameras")
def ops_certify_cameras(session: Session = Depends(get_db)) -> dict[str, Any]:
    from app.sold.certify import live_camera_body_certification

    return live_camera_body_certification(session)


@router.get("/ops/camera-pipeline")
def ops_camera_pipeline(session: Session = Depends(get_db)) -> dict[str, Any]:
    """Live book snapshot for the camera sold-data chain."""
    from app.sold.certify import live_camera_body_certification
    from app.sold.quality import sold_quality_report
    from app.evidence.providers.compsniper import compsniper_health
    from app.identity.product_class import CAMERA_BODY, classify_listing
    from app.opportunity.book import current_generation, is_current_opportunity

    generation = current_generation(session)
    opps = [
        opp
        for opp in session.scalars(select(Opportunity).limit(2000)).all()
        if is_current_opportunity(opp, generation)
    ]
    listing_ids = [opp.listing_id for opp in opps]
    listings_by_id = {}
    if listing_ids:
        for row in session.scalars(select(Listing).where(Listing.id.in_(listing_ids))).all():
            listings_by_id[row.id] = row
    rows = []
    for opp in opps:
        listing = listings_by_id.get(opp.listing_id)
        pack = opp.provenance_pack or {}
        whyv = pack.get("why_this_value") or {}
        product_class = pack.get("product_class") or ""
        title = listing.title if listing else ""
        if not product_class and title:
            product_class = classify_listing(title, listing.description if listing else "").product_class
        if product_class and product_class != CAMERA_BODY:
            continue
        rows.append(
            {
                "id": str(opp.id),
                "title": title,
                "url": listing.url if listing else "",
                "ask": str(listing.asking_price) if listing and listing.asking_price is not None else None,
                "currency": listing.currency if listing else None,
                "country": listing.country if listing else None,
                "sold_n": whyv.get("realised_comp_count") or 0,
                "p25": whyv.get("p25"),
                "median": whyv.get("median"),
                "expected": str(opp.expected_resale_eur),
                "quick": whyv.get("quick_sale") or whyv.get("p25"),
                "max_buy": str(opp.max_buy_eur),
                "expected_profit": str(opp.expected_profit_eur),
                "downside": str(opp.downside_profit_eur),
                "roi": str(opp.expected_roi),
                "velocity": (pack.get("liquidity") or {}).get("kind"),
                "confidence": str(opp.valuation_confidence),
                "decision": opp.money_ready_decision,
                "failed_gates": (opp.gate_results or {}).get("failures") or [],
                "value_status": getattr(opp, "value_status", None),
                "algorithm_version": getattr(opp, "algorithm_version", None),
                "product_class": product_class,
                "valuation_run_id": str(getattr(opp, "valuation_run_id", "") or ""),
            }
        )
    rows.sort(key=lambda r: float(r.get("expected_profit") or 0), reverse=True)
    return {
        "compsniper": compsniper_health(),
        "sold_quality": sold_quality_report(session, rematch=False),
        "certification": live_camera_body_certification(session),
        "scheduler": scheduler_status(),
        "book": {
            "algorithm_version": VALUATION_ALGORITHM_VERSION,
            "generation_id": str(generation.id) if generation else None,
            "generation_status": generation.status if generation else None,
        },
        "top20": rows[:20],
        "buy_ready": [r for r in rows if r["decision"] == "BUY_READY"],
        "count": len(rows),
    }
