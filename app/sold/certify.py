"""Empirical camera_body certification. Never override a failing bar."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.certification.engine import CategoryMetrics, evaluate_category_certification
from app.liquidity.realized import sold_velocity
from app.models.orm import Listing, Opportunity, SoldEvidence, SoldQueryCache
from app.sold.backtest_sold import synthetic_lookahead_backtest
from app.sold.cache import cache_is_successful
from app.sold.cameras import camera_from_identity
from app.sold.identity_gate import measure_identity_precision
from app.sold.refresh import evidence_freshness_from_rows

_LIVE_CACHE: tuple[float, dict[str, Any]] | None = None


def camera_body_certification_snapshot(
    *,
    precision: dict[str, Any],
    backtest: dict[str, Any] | None = None,
    listings: int = 0,
    realised_comp_coverage: Decimal = Decimal("0"),
    condition_reliable_rate: Decimal = Decimal("0.85"),
    exit_channel_credible: bool = False,
    risk_controls_pass: bool = False,
) -> dict[str, Any]:
    """Certify camera_body only from measured bars."""
    identity_rate = Decimal(str(precision.get("exact_match_precision") or 0))
    fp = Decimal(str(precision.get("accepted_wrong") or 0))
    sample = int(precision.get("sample_size") or 0)
    false_positive_rate = (fp / Decimal(sample)) if sample else Decimal("1")
    mae_ok = True
    if backtest and backtest.get("mean_pct_error") is not None:
        try:
            mae_ok = Decimal(str(backtest["mean_pct_error"])) <= Decimal("0.20")
        except Exception:
            mae_ok = False
    extra_reasons: list[str] = []
    if backtest:
        freshness = backtest.get("evidence_freshness_rate")
        liquidity = backtest.get("liquidity_coverage")
        costs = backtest.get("cost_completeness")
        if freshness is not None and Decimal(str(freshness)) < Decimal("0.50"):
            extra_reasons.append(f"evidence_freshness {freshness} < 0.50")
        if liquidity is not None and Decimal(str(liquidity)) < Decimal("0.40"):
            extra_reasons.append(f"liquidity {liquidity} < 0.40")
        if costs is not None and Decimal(str(costs)) < Decimal("0.80"):
            extra_reasons.append(f"cost_completeness {costs} < 0.80")
    metrics = CategoryMetrics(
        category="cameras",
        listings=listings,
        false_positive_rate=false_positive_rate,
        identity_exact_or_variant_rate=identity_rate,
        condition_reliable_rate=condition_reliable_rate,
        realised_comp_coverage=realised_comp_coverage,
        valuation_error_ok=mae_ok,
        exit_channel_credible=exit_channel_credible,
        risk_controls_pass=risk_controls_pass,
    )
    verdict = evaluate_category_certification(metrics)
    reasons = list(verdict.reasons)
    if extra_reasons and verdict.certified:
        reasons = extra_reasons
    elif extra_reasons:
        reasons = reasons + extra_reasons
    certified = not extra_reasons and verdict.certified
    return {
        "category": "camera_body",
        "certified": certified,
        "reasons": reasons if not certified else ["all_certification_bars_met"],
        "identity_precision": float(identity_rate),
        "false_positive_rate": float(false_positive_rate),
        "realised_comp_coverage": str(realised_comp_coverage),
        "listings": listings,
        "evidence_freshness_rate": str((backtest or {}).get("evidence_freshness_rate") or ""),
        "liquidity_coverage": str((backtest or {}).get("liquidity_coverage") or ""),
        "cost_completeness": str((backtest or {}).get("cost_completeness") or ""),
        "note": (
            "Certified on measured identity, coverage, valuation error, and exit bars."
            if certified
            else "Uncertified until live realised coverage and remaining bars pass. Not overridden."
        ),
    }


def live_camera_body_certification(session: Session, *, ttl_seconds: float = 600.0) -> dict[str, Any]:
    """Measure camera_body bars from the live book. Never override a fail."""
    global _LIVE_CACHE
    now = datetime.now(timezone.utc).timestamp()
    if _LIVE_CACHE and (now - _LIVE_CACHE[0]) < ttl_seconds:
        return _LIVE_CACHE[1]

    precision = measure_identity_precision()
    backtest = synthetic_lookahead_backtest()
    listings = session.scalars(select(Listing).where(Listing.status == "active")).all()
    cameras = []
    from app.identity.product_class import CAMERA_BODY, classify_listing
    from app.sold.cameras import CAMERA_BODIES

    for listing in listings:
        extras = listing.extras or {}
        product_class = (extras.get("product_class") or "").lower()
        if not product_class:
            product_class = classify_listing(listing.title or "", listing.description or "").product_class
        if product_class != CAMERA_BODY:
            continue
        body = camera_from_identity(brand=listing.brand, model=listing.model, title=listing.title or "")
        if body is not None:
            cameras.append((listing, body))
    sold_rows = session.scalars(select(SoldEvidence)).all()
    sold_by_product: dict[str, list] = {}
    for row in sold_rows:
        sold_by_product.setdefault(row.canonical_product_id, []).append(row)
    cache_rows = session.scalars(select(SoldQueryCache)).all()
    cache_by_product: dict[str, list] = {}
    for row in cache_rows:
        cache_by_product.setdefault(row.canonical_product_id, []).append(row)
    covered = 0
    fresh_n = 0
    liquid_n = 0
    condition_n = 0
    for listing, body in cameras:
        rows = sold_by_product.get(body.canonical_id) or []
        n_accepted = sum(1 for r in rows if (r.extras or {}).get("accepted_for_valuation") is not False)
        if n_accepted >= 3:
            covered += 1
        cache_ok = any(cache_is_successful(row) for row in cache_by_product.get(body.canonical_id) or [])
        freshness = evidence_freshness_from_rows(rows, cache_ok=cache_ok)
        if freshness.get("fresh"):
            fresh_n += 1
        velocity = sold_velocity(session, body.canonical_id, rows=rows)
        if str(velocity.get("kind") or "UNKNOWN") != "UNKNOWN":
            liquid_n += 1
        if (listing.condition_grade or "").lower() not in {"", "unknown"}:
            condition_n += 1
    n = len(cameras) or 1
    coverage = Decimal(covered) / Decimal(n) if cameras else Decimal("0")
    condition_rate = Decimal(condition_n) / Decimal(n) if cameras else Decimal("0")
    freshness_rate = Decimal(fresh_n) / Decimal(n) if cameras else Decimal("0")
    liquidity_rate = Decimal(liquid_n) / Decimal(n) if cameras else Decimal("0")
    opps = session.scalars(select(Opportunity).limit(2000)).all()
    listing_ids = [opp.listing_id for opp in opps]
    listings_by_id = {}
    if listing_ids:
        for row in session.scalars(select(Listing).where(Listing.id.in_(listing_ids))).all():
            listings_by_id[row.id] = row
    from app.opportunity.book import current_generation, is_current_opportunity

    generation = current_generation(session)
    camera_opps = []
    for opp in opps:
        if not is_current_opportunity(opp, generation):
            continue
        listing = listings_by_id.get(opp.listing_id)
        if listing is None:
            continue
        pack = opp.provenance_pack or {}
        product_class = (pack.get("product_class") or (listing.extras or {}).get("product_class") or "").lower()
        if product_class == CAMERA_BODY:
            camera_opps.append(opp)
    cost_ok = 0
    exit_ok = 0
    for opp in camera_opps:
        breakdown = opp.cost_breakdown or {}
        if breakdown:
            cost_ok += 1
        if opp.best_exit_channel:
            exit_ok += 1
    cost_rate = Decimal(cost_ok) / Decimal(len(camera_opps)) if camera_opps else Decimal("0")
    exit_channel_credible = bool(camera_opps) and exit_ok >= max(1, int(0.5 * len(camera_opps)))
    from app.core.config import settings

    risk_evaluated = 0
    for opp in camera_opps:
        gates = (opp.gate_results or {}).get("gates") or {}
        if "RISK_PASS" in gates:
            risk_evaluated += 1
    risk_controls_pass = (
        bool(settings.safe_start_mode)
        and bool(settings.buy_ready_require_realised)
        and bool(camera_opps)
        and risk_evaluated >= max(1, int(0.5 * len(camera_opps)))
    )
    live_backtest = dict(backtest)
    live_backtest["evidence_freshness_rate"] = str(freshness_rate)
    live_backtest["liquidity_coverage"] = str(liquidity_rate)
    live_backtest["cost_completeness"] = str(cost_rate)
    snapshot = camera_body_certification_snapshot(
        precision=precision,
        backtest=live_backtest,
        listings=len(cameras),
        realised_comp_coverage=coverage,
        condition_reliable_rate=condition_rate if cameras else Decimal("0"),
        exit_channel_credible=exit_channel_credible,
        risk_controls_pass=risk_controls_pass,
    )
    now_dt = datetime.now(timezone.utc)
    bodies_report: list[dict[str, Any]] = []
    needs_refresh: list[str] = []
    for body in CAMERA_BODIES:
        rows = sold_by_product.get(body.canonical_id) or []
        accepted = [
            row
            for row in rows
            if (row.extras or {}).get("accepted_for_valuation") is not False
            and (row.source or "") == "compsniper"
        ]
        dates = [row.sold_date for row in accepted if row.sold_date]
        caches = cache_by_product.get(body.canonical_id) or []
        cache_ok = any(cache_is_successful(row) for row in caches)
        freshness = evidence_freshness_from_rows(rows, cache_ok=cache_ok)
        last_refresh = max((row.queried_at for row in caches if row.queried_at), default=None)
        if last_refresh is not None and last_refresh.tzinfo is None:
            last_refresh = last_refresh.replace(tzinfo=timezone.utc)
        cache_age = (now_dt - last_refresh).days if last_refresh else None
        listing_n = sum(1 for _, matched in cameras if matched.canonical_id == body.canonical_id)
        newest = max(dates) if dates else None
        oldest = min(dates) if dates else None
        rec = {
            "canonical_id": body.canonical_id,
            "accepted_n": len(accepted),
            "newest_accepted": newest.isoformat() if newest else None,
            "oldest_accepted": oldest.isoformat() if oldest else None,
            "fresh": bool(freshness.get("fresh")),
            "freshness_reason": freshness.get("reason"),
            "age_days": freshness.get("age_days"),
            "cache_ok": cache_ok,
            "cache_age_days": cache_age,
            "last_sold_refresh": last_refresh.isoformat() if last_refresh else None,
            "camera_body_listings": listing_n,
        }
        bodies_report.append(rec)
        if listing_n and not rec["fresh"]:
            needs_refresh.append(body.canonical_id)
    snapshot["live"] = True
    snapshot["camera_listings"] = len(cameras)
    snapshot["covered_listings"] = covered
    snapshot["bodies"] = bodies_report
    snapshot["freshness_needs_refresh"] = needs_refresh
    snapshot["freshness_note"] = (
        "Freshness is accepted CompSniper tickets ≤21d AND a successful in-TTL cache. "
        "Threshold remains 0.50. Do not lower it. Refresh only the listed canonical ids."
    )
    _LIVE_CACHE = (now, snapshot)
    return snapshot
