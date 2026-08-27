"""Quota-aware CompSniper sold-evidence refresh.

One product/marketplace lookup, cached. New accepted tickets trigger revaluation
of matching active opportunities.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.evidence.providers.compsniper import CompSniperProvider, HEALTH, compsniper_health
from app.models.orm import Listing, SoldEvidence
from app.observability.metrics import record_metric
from app.sold.cache import cache_is_fresh, cache_is_successful, get_cache, upsert_cache
from app.sold.cameras import CAMERA_BODIES, CameraBody, camera_from_identity, query_plan_for
from app.sold.normalize import CanonicalSoldRecord, normalize_item
from app.sold.persist import persist_canonical_sold

logger = get_logger("arie.sold.refresh")

PRIMARY_MARKETS = ("GB", "DE", "FR")
UK_ENOUGH = 12
MIN_QUOTA_RESERVE = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fx_map(session: Session) -> dict[str, Decimal]:
    from app.models.orm import FxRate

    rows = session.scalars(select(FxRate).order_by(FxRate.as_of.desc()).limit(40)).all()
    rates: dict[str, Decimal] = {}
    for row in rows:
        if row.quote and row.quote not in rates:
            rates[row.quote] = row.rate
    return rates


def bodies_from_active_listings(session: Session, *, limit: int = 80) -> list[CameraBody]:
    listings = session.scalars(
        select(Listing).where(Listing.status == "active").order_by(Listing.last_seen_at.desc()).limit(400)
    ).all()
    found: dict[str, CameraBody] = {}
    for listing in listings:
        body = camera_from_identity(
            brand=listing.brand,
            model=listing.model,
            canonical_key=None,
            title=listing.title or "",
        )
        cat = (listing.category or "").lower()
        if body is None and cat not in {"cameras", "camera", ""}:
            continue
        if body is None:
            continue
        found[body.canonical_id] = body
        if len(found) >= limit:
            break
    if not found:
        return list(CAMERA_BODIES)
    # Keep catalogue order for stable quota use.
    return [body for body in CAMERA_BODIES if body.canonical_id in found]


async def refresh_one_query(
    session: Session,
    body: CameraBody,
    plan: dict[str, str],
    *,
    rates: dict[str, Decimal],
    provider: CompSniperProvider,
    force: bool = False,
) -> dict[str, Any]:
    cached = get_cache(
        session,
        canonical_product_id=plan["canonical_product_id"],
        variant=plan.get("variant") or "body",
        marketplace=plan["marketplace"],
        condition_bucket=plan.get("condition_bucket") or "used",
    )
    if cache_is_fresh(cached) and not force:
        HEALTH.cache_hits += 1
        record_metric(
            session,
            "sold_cache_hit",
            run_id=plan["canonical_product_id"],
            marketplace=plan["marketplace"],
        )
        return {
            "ok": True,
            "cache": "hit",
            "canonical_product_id": plan["canonical_product_id"],
            "marketplace": plan["marketplace"],
            "accepted": cached.accepted_count if cached else 0,
            "raw": cached.raw_count if cached else 0,
            "queried": False,
        }
    HEALTH.cache_misses += 1
    if HEALTH.quota_remaining is not None and HEALTH.quota_remaining <= MIN_QUOTA_RESERVE:
        return {
            "ok": False,
            "cache": "miss",
            "canonical_product_id": plan["canonical_product_id"],
            "marketplace": plan["marketplace"],
            "error": "quota_reserve",
            "queried": False,
        }
    page = await provider.scrape(
        plan["keyword"],
        ebay_site=plan["ebay_site"],
        count=240,
        page=1,
        category_id=plan.get("category_id"),
        item_condition="used",
        sold=True,
    )
    record_metric(
        session,
        "compsniper_requests",
        run_id=plan["canonical_product_id"],
        marketplace=plan["marketplace"],
        http_status=page.http_status,
    )
    if not page.ok:
        upsert_cache(
            session,
            canonical_product_id=plan["canonical_product_id"],
            variant=plan.get("variant") or "body",
            marketplace=plan["marketplace"],
            condition_bucket=plan.get("condition_bucket") or "used",
            keyword=plan["keyword"],
            raw_count=0,
            accepted_count=cached.accepted_count if cached else 0,
            rejected_count=0,
            last_http_status=page.http_status,
            quota_remaining=HEALTH.quota_remaining,
            extras={"error": page.error, "code": page.error_code},
        )
        return {
            "ok": False,
            "cache": "miss",
            "canonical_product_id": plan["canonical_product_id"],
            "marketplace": plan["marketplace"],
            "error": page.error_code or page.error,
            "http_status": page.http_status,
            "queried": True,
        }
    records: list[CanonicalSoldRecord] = [
        normalize_item(item, target=body, ebay_site=plan["ebay_site"], rates=rates) for item in page.items
    ]
    persist_stats = persist_canonical_sold(session, records)
    accepted = sum(1 for rec in records if rec.accepted_for_valuation)
    rejected = len(records) - accepted
    cutoff_30 = _now() - timedelta(days=30)
    sales_30d = sum(1 for rec in records if rec.accepted_for_valuation and rec.sold_at >= cutoff_30)
    upsert_cache(
        session,
        canonical_product_id=plan["canonical_product_id"],
        variant=plan.get("variant") or "body",
        marketplace=plan["marketplace"],
        condition_bucket=plan.get("condition_bucket") or "used",
        keyword=plan["keyword"],
        raw_count=len(records),
        accepted_count=accepted,
        rejected_count=rejected,
        last_http_status=page.http_status,
        quota_remaining=HEALTH.quota_remaining,
        extras={"persist": persist_stats, "keyword": plan["keyword"]},
        sales_30d=sales_30d,
    )
    record_metric(session, "realised_hits", value=accepted, run_id=plan["canonical_product_id"])
    record_metric(session, "sold_rejected", value=rejected, run_id=plan["canonical_product_id"])
    return {
        "ok": True,
        "cache": "miss",
        "canonical_product_id": plan["canonical_product_id"],
        "marketplace": plan["marketplace"],
        "raw": len(records),
        "accepted": accepted,
        "rejected": rejected,
        "imported": persist_stats.get("imported"),
        "queried": True,
        "new_accepted": persist_stats.get("imported_accepted", 0),
    }


async def refresh_sold_evidence(
    session: Session,
    *,
    bodies: list[CameraBody] | None = None,
    force: bool = False,
    markets: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    health = compsniper_health()
    if health["status"] in {"DISABLED", "BLOCKED_CREDENTIALS"}:
        return {"ok": False, "reason": health["status"], "health": health, "queries": []}
    rates = _fx_map(session)
    provider = CompSniperProvider()
    targets = bodies if bodies is not None else bodies_from_active_listings(session)
    market_order = markets or tuple(
        part.strip().upper()
        for part in str(getattr(settings, "compsniper_primary_marketplaces", "GB,DE,FR")).split(",")
        if part.strip()
    ) or PRIMARY_MARKETS
    queries: list[dict[str, Any]] = []
    revalue_ids: set[str] = set()
    for body in targets:
        uk_accepted = 0
        for plan in query_plan_for(body, marketplaces=market_order):
            if plan["marketplace"] != "GB" and uk_accepted >= UK_ENOUGH:
                queries.append(
                    {
                        "ok": True,
                        "skipped": "uk_sufficient",
                        "canonical_product_id": body.canonical_id,
                        "marketplace": plan["marketplace"],
                        "queried": False,
                    }
                )
                continue
            result = await refresh_one_query(
                session, body, plan, rates=rates, provider=provider, force=force
            )
            queries.append(result)
            if plan["marketplace"] == "GB":
                uk_accepted = int(result.get("accepted") or 0)
            if int(result.get("new_accepted") or 0) > 0:
                revalue_ids.add(body.canonical_id)
            if result.get("error") in {"quota_exceeded", "quota_reserve", "unauthorized"}:
                break
        else:
            continue
        break
    revalued = 0
    if revalue_ids:
        revalued = await revalue_matching(session, revalue_ids)
    return {
        "ok": True,
        "health": compsniper_health(),
        "products": [b.canonical_id for b in targets],
        "queries": queries,
        "revalued": revalued,
        "requested_new_evidence": sorted(revalue_ids),
    }


async def revalue_matching(session: Session, canonical_ids: set[str]) -> int:
    from app.pipeline.service import refresh_fx, evaluate_listing, _comps_for
    from app.identity.resolvers import identify_with_resolvers
    from app.condition.category import assess_category_condition

    rates = await refresh_fx(session)
    listings = session.scalars(select(Listing).where(Listing.status == "active").limit(400)).all()
    written = 0
    for listing in listings:
        body = camera_from_identity(brand=listing.brand, model=listing.model, title=listing.title or "")
        if body is None or body.canonical_id not in canonical_ids:
            continue
        identity = identify_with_resolvers(
            title=listing.title,
            description=listing.description or "",
            brand_hint=listing.brand,
            model_hint=listing.model,
            category=listing.category,
        )
        extras = listing.extras or {}
        condition = assess_category_condition(
            listing.condition_raw,
            "\n".join([listing.description or "", str(extras.get("conditionDescription") or "")]),
            identity.category or listing.category,
            condition_id=str(extras.get("conditionId") or "") or None,
            specifics=extras.get("itemSpecifics") if isinstance(extras.get("itemSpecifics"), dict) else None,
        )
        listing._identity = identity  # type: ignore[attr-defined]
        listing._condition = condition  # type: ignore[attr-defined]
        comps = await _comps_for(listing, rates, session)
        evaluate_listing(session, listing, comps, rates)
        written += 1
    session.flush()
    return written


async def ensure_sold_for_listing(session: Session, listing: Listing, rates: dict[str, Decimal]) -> dict[str, Any]:
    body = camera_from_identity(brand=listing.brand, model=listing.model, title=listing.title or "")
    if body is None:
        return {"ok": False, "reason": "not_camera_body"}
    return await refresh_sold_evidence(session, bodies=[body], markets=("GB", "DE", "FR"))


def evidence_freshness(
    session: Session, canonical_product_id: str, *, max_age_days: int | None = None
) -> dict[str, Any]:
    max_age = max_age_days or int(getattr(settings, "compsniper_buy_ready_max_evidence_age_days", 21) or 21)
    rows = session.scalars(
        select(SoldEvidence).where(SoldEvidence.canonical_product_id == canonical_product_id)
    ).all()
    accepted = [
        row
        for row in rows
        if (row.extras or {}).get("accepted_for_valuation", True) is not False
        and (row.source or "") == "compsniper"
    ]
    if not accepted:
        return {"fresh": False, "reason": "no_accepted_sold", "n": 0, "age_days": None}
    newest = max(row.sold_date for row in accepted if row.sold_date)
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=timezone.utc)
    age = (_now() - newest).days
    cache_rows = [
        get_cache(session, canonical_product_id=canonical_product_id, marketplace=m)
        for m in ("GB", "DE", "FR")
    ]
    cache_fresh = any(cache_is_successful(row) for row in cache_rows if row)
    stale_reason = ""
    if not cache_fresh:
        stale_reason = "stale_cache"
        failed = [row for row in cache_rows if row and row.last_http_status not in {200, None}]
        if failed:
            codes = {int(row.last_http_status) for row in failed if row.last_http_status}
            if 401 in codes:
                stale_reason = "provider_unauthorized"
            elif 429 in codes:
                stale_reason = "provider_rate_limited"
            elif any(code >= 500 for code in codes):
                stale_reason = "provider_outage"
    fresh = age <= max_age and cache_fresh
    return {
        "fresh": fresh,
        "reason": "" if fresh else (stale_reason or "stale_sold_dates"),
        "n": len(accepted),
        "age_days": age,
        "max_age_days": max_age,
    }
