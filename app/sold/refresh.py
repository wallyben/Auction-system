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
from app.jobs.lease import heartbeat, maybe_yield, yield_loop
from app.models.orm import Listing, SoldEvidence
from app.observability.metrics import record_metric
from app.sold.cache import cache_is_fresh, cache_is_successful, get_cache, upsert_cache
from app.sold.cameras import CAMERA_BODIES, CameraBody, camera_from_identity, query_plan_for
from app.sold.normalize import CanonicalSoldRecord, normalize_item
from app.sold.persist import persist_canonical_sold
from app.valuation.version import VALUATION_ALGORITHM_VERSION

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


def _item_from_sold_row(row: SoldEvidence):
    """Rebuild a CompSniper item from stored extras/raw. Never calls the provider."""
    from app.evidence.providers.compsniper import CompSniperItem, parse_item

    extras = row.extras or {}
    raw = extras.get("raw")
    if isinstance(raw, dict) and raw:
        parsed = parse_item(raw)
        if parsed is not None:
            if extras.get("best_offer_accepted"):
                parsed.best_offer_accepted = True
            return parsed
    title = str(extras.get("title") or "")
    if not title:
        return None
    native = extras.get("sold_price_native")
    shipping_native = extras.get("shipping_native")
    currency = str(extras.get("native_currency") or row.currency or "EUR")
    try:
        sold_price = Decimal(str(native)) if native not in (None, "") else Decimal(str(row.sold_price))
    except Exception:
        sold_price = Decimal(str(row.sold_price or 0))
    try:
        shipping_price = Decimal(str(shipping_native)) if shipping_native not in (None, "") else None
    except Exception:
        shipping_price = None
    listing_type = str(extras.get("listing_type") or "sold")
    return CompSniperItem(
        item_id=str(extras.get("source_listing_id") or row.url_or_reference or row.id),
        url=row.url_or_reference,
        epid=None,
        title=title,
        condition=str(extras.get("condition_raw") or row.condition or "") or None,
        condition_id=None,
        buying_format=None,
        best_offer_accepted=bool(extras.get("best_offer_accepted")),
        listing_type=listing_type,
        ended_at=row.sold_date,
        sold_price=sold_price,
        sold_currency=currency,
        shipping_price=shipping_price,
        shipping_currency=currency,
        shipping_type=None,
        total_price=None,
        seller_username=None,
        seller_positive_percent=None,
        seller_feedback_score=None,
        item_location=None,
        scraped_at=None,
        raw=raw if isinstance(raw, dict) else {},
    )


async def revalidate_stored_sold_evidence(
    session: Session, *, rates: dict[str, Decimal] | None = None, job=None
) -> dict[str, Any]:
    """Re-run identity/normalize on stored tickets. Uses zero CompSniper quota."""
    from app.sold.cameras import MARKETPLACE_SITES, camera_by_id

    fx = rates if rates is not None else _fx_map(session)
    rows = session.scalars(select(SoldEvidence).where(SoldEvidence.source == "compsniper")).all()
    site_by_territory = {territory: site for territory, site in MARKETPLACE_SITES}
    records: list[CanonicalSoldRecord] = []
    touched: list[SoldEvidence] = []
    flipped_to_reject = 0
    flipped_to_accept = 0
    unchanged = 0
    skipped = 0
    changed_product_ids: set[str] = set()
    for index, row in enumerate(rows):
        body = camera_by_id(row.canonical_product_id)
        item = _item_from_sold_row(row)
        if body is None or item is None:
            skipped += 1
            continue
        site = site_by_territory.get((row.territory or "GB").upper(), "ebay.co.uk")
        rec = normalize_item(item, target=body, ebay_site=site, rates=fx)
        extras = row.extras or {}
        if rec.sold_price_eur is None and extras.get("sold_price_eur") not in (None, ""):
            try:
                rec.sold_price_eur = Decimal(str(extras["sold_price_eur"]))
            except Exception:
                pass
        if rec.shipping_eur is None and extras.get("shipping_eur") not in (None, ""):
            try:
                rec.shipping_eur = Decimal(str(extras["shipping_eur"]))
            except Exception:
                pass
        was = extras.get("accepted_for_valuation") is not False
        now_accepted = rec.accepted_for_valuation
        if was != now_accepted:
            changed_product_ids.add(row.canonical_product_id)
            if was and not now_accepted:
                flipped_to_reject += 1
            else:
                flipped_to_accept += 1
        else:
            unchanged += 1
        records.append(rec)
        touched.append(row)
        await maybe_yield(index, every=25)
        if job is not None and index > 0 and index % 80 == 0:
            heartbeat(session, job)
    if records:
        persist_canonical_sold(session, records)
        stamp = _now().isoformat()
        for row in touched:
            extras = dict(row.extras or {})
            extras["revalidated_at"] = stamp
            extras["matching_rules_version"] = VALUATION_ALGORITHM_VERSION
            row.extras = extras
        session.flush()
        await yield_loop()
    return {
        "ok": True,
        "examined": len(rows),
        "updated": len(records),
        "skipped": skipped,
        "flipped_to_reject": flipped_to_reject,
        "flipped_to_accept": flipped_to_accept,
        "unchanged": unchanged,
        "changed_product_ids": sorted(changed_product_ids),
        "quota_used": 0,
    }


async def refresh_sold_evidence(
    session: Session,
    *,
    bodies: list[CameraBody] | None = None,
    force: bool = False,
    markets: tuple[str, ...] | None = None,
    revalidate: bool = False,
) -> dict[str, Any]:
    rates = _fx_map(session)
    reval: dict[str, Any] = {"ok": True, "skipped": True, "quota_used": 0}
    revalue_ids: set[str] = set()
    if revalidate:
        reval = await revalidate_stored_sold_evidence(session, rates=rates)
        revalue_ids = set(reval.get("changed_product_ids") or [])
    health = compsniper_health()
    if health["status"] in {"DISABLED", "BLOCKED_CREDENTIALS"}:
        revalued = await revalue_matching(session, revalue_ids) if revalue_ids else 0
        return {
            "ok": False,
            "reason": health["status"],
            "health": health,
            "queries": [],
            "revalidate": reval,
            "revalued": revalued,
        }
    provider = CompSniperProvider()
    targets = bodies if bodies is not None else bodies_from_active_listings(session)
    market_order = markets or tuple(
        part.strip().upper()
        for part in str(getattr(settings, "compsniper_primary_marketplaces", "GB,DE,FR")).split(",")
        if part.strip()
    ) or PRIMARY_MARKETS
    queries: list[dict[str, Any]] = []
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
        "revalidate": reval,
    }


async def revalue_matching(session: Session, canonical_ids: set[str], *, job=None) -> int:
    from app.pipeline.service import refresh_fx, evaluate_listing, _comps_for
    from app.identity.resolvers import identify_with_resolvers
    from app.condition.category import assess_category_condition
    from app.sold.certify import live_camera_body_certification

    rates = await refresh_fx(session)
    live_cert = live_camera_body_certification(session)
    listings = session.scalars(select(Listing).where(Listing.status == "active").limit(400)).all()
    written = 0
    for index, listing in enumerate(listings):
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
        comps = await _comps_for(listing, rates, session, refresh_sold=False)
        evaluate_listing(session, listing, comps, rates, live_cert=live_cert)
        written += 1
        await maybe_yield(index, every=4)
        if job is not None and written > 0 and written % 10 == 0:
            heartbeat(session, job)
    session.flush()
    return written


async def ensure_sold_for_listing(session: Session, listing: Listing, rates: dict[str, Decimal]) -> dict[str, Any]:
    body = camera_from_identity(brand=listing.brand, model=listing.model, title=listing.title or "")
    if body is None:
        return {"ok": False, "reason": "not_camera_body"}
    cached = get_cache(session, canonical_product_id=body.canonical_id, marketplace="GB")
    if cache_is_successful(cached):
        return {
            "ok": True,
            "skipped": "fresh_cache",
            "canonical_product_id": body.canonical_id,
            "quota_used": 0,
        }
    # Listing evaluation never spends CompSniper quota. Scheduled /ops sold-refresh does.
    return {
        "ok": True,
        "skipped": "no_paid_refresh_on_eval",
        "canonical_product_id": body.canonical_id,
        "quota_used": 0,
    }


def evidence_freshness_from_rows(
    rows: list[SoldEvidence],
    *,
    cache_ok: bool,
    max_age_days: int | None = None,
    now: datetime | None = None,
    stale_reason: str = "stale_cache",
) -> dict[str, Any]:
    now = now or _now()
    max_age = max_age_days or int(getattr(settings, "compsniper_buy_ready_max_evidence_age_days", 21) or 21)
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
    age = (now - newest).days
    fresh = age <= max_age and cache_ok
    return {
        "fresh": fresh,
        "reason": "" if fresh else (stale_reason if not cache_ok else "stale_sold_dates"),
        "n": len(accepted),
        "age_days": age,
        "max_age_days": max_age,
    }


def evidence_freshness(
    session: Session, canonical_product_id: str, *, max_age_days: int | None = None
) -> dict[str, Any]:
    rows = session.scalars(
        select(SoldEvidence).where(SoldEvidence.canonical_product_id == canonical_product_id)
    ).all()
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
    return evidence_freshness_from_rows(
        rows, cache_ok=cache_fresh, max_age_days=max_age_days, stale_reason=stale_reason or "stale_cache"
    )
