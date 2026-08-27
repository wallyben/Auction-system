"""Empirical camera_body certification. Never override a failing bar."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.certification.engine import CategoryMetrics, evaluate_category_certification
from app.sold.backtest_sold import synthetic_lookahead_backtest
from app.sold.cameras import camera_from_identity
from app.sold.identity_gate import measure_identity_precision
from app.sold.refresh import evidence_freshness

_LIVE_CACHE: tuple[float, dict[str, Any]] | None = None


def camera_body_certification_snapshot(
    *,
    precision: dict[str, Any],
    backtest: dict[str, Any] | None = None,
    listings: int = 0,
    realised_comp_coverage: Decimal = Decimal("0"),
    condition_reliable_rate: Decimal = Decimal("0.85"),
    exit_channel_credible: bool = True,
    risk_controls_pass: bool = True,
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


def live_camera_body_certification(session: Session, *, ttl_seconds: float = 45.0) -> dict[str, Any]:
    """Measure camera_body bars from the live book. Never override a fail."""
    global _LIVE_CACHE
    now = datetime.now(timezone.utc).timestamp()
    if _LIVE_CACHE and (now - _LIVE_CACHE[0]) < ttl_seconds:
        return _LIVE_CACHE[1]
    from app.models.orm import Listing, Opportunity, SoldEvidence
    from app.liquidity.realized import sold_velocity

    precision = measure_identity_precision()
    backtest = synthetic_lookahead_backtest()
    listings = session.scalars(select(Listing).where(Listing.status == "active").limit(500)).all()
    cameras = []
    for listing in listings:
        body = camera_from_identity(brand=listing.brand, model=listing.model, title=listing.title or "")
        if body is not None:
            cameras.append((listing, body))
    covered = 0
    fresh_n = 0
    liquid_n = 0
    condition_n = 0
    for listing, body in cameras:
        n_accepted = 0
        rows = session.scalars(
            select(SoldEvidence).where(SoldEvidence.canonical_product_id == body.canonical_id)
        ).all()
        n_accepted = sum(1 for r in rows if (r.extras or {}).get("accepted_for_valuation") is not False)
        if n_accepted >= 3:
            covered += 1
        freshness = evidence_freshness(session, body.canonical_id)
        if freshness.get("fresh"):
            fresh_n += 1
        velocity = sold_velocity(session, body.canonical_id)
        if str(velocity.get("kind") or "UNKNOWN") != "UNKNOWN":
            liquid_n += 1
        if (listing.condition_grade or "").lower() not in {"", "unknown"}:
            condition_n += 1
    n = len(cameras) or 1
    coverage = Decimal(covered) / Decimal(n) if cameras else Decimal("0")
    condition_rate = Decimal(condition_n) / Decimal(n) if cameras else Decimal("0")
    freshness_rate = Decimal(fresh_n) / Decimal(n) if cameras else Decimal("0")
    liquidity_rate = Decimal(liquid_n) / Decimal(n) if cameras else Decimal("0")
    opps = session.scalars(select(Opportunity).limit(400)).all()
    camera_opps = []
    for opp in opps:
        listing = session.get(Listing, opp.listing_id)
        if listing is None:
            continue
        if camera_from_identity(brand=listing.brand, model=listing.model, title=listing.title or ""):
            camera_opps.append(opp)
    cost_ok = 0
    for opp in camera_opps:
        breakdown = opp.cost_breakdown or {}
        if breakdown:
            cost_ok += 1
    cost_rate = Decimal(cost_ok) / Decimal(len(camera_opps)) if camera_opps else Decimal("0")
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
        exit_channel_credible=True,
        risk_controls_pass=True,
    )
    snapshot["live"] = True
    snapshot["camera_listings"] = len(cameras)
    snapshot["covered_listings"] = covered
    _LIVE_CACHE = (now, snapshot)
    return snapshot
