"""Live sold-ticket quality report. Maps ARIE reasons to commercial rejection codes."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import SoldEvidence, SoldQueryCache
from app.sold.cameras import CAMERA_BODIES
from app.sold.identity_gate import measure_identity_precision, validate_camera_sold

REASON_CODES = {
    "accessory": "ACCESSORY",
    "wrong_model": "WRONG_MODEL",
    "wrong_model_family": "WRONG_GENERATION",
    "kit_or_bundle": "KIT",
    "lens_not_body": "LENS",
    "parts_or_broken": "PARTS",
    "invalid_sold_price": "INVALID_PRICE",
    "implausible_date": "INVALID_DATE",
    "not_completed_sale": "INVALID_DATE",
    "invalid_currency": "INVALID_PRICE",
    "best_offer_upper_bound": "BEST_OFFER_UPPER_BOUND",
    "wrong_product_class": "WRONG_MODEL",
}


def _code(reason: str) -> str:
    text = (reason or "").lower()
    if "bundle" in text:
        return "BUNDLE"
    if "broken" in text or "repair" in text:
        return "BROKEN"
    if "duplicate" in text:
        return "DUPLICATE"
    return REASON_CODES.get(reason, (reason or "OTHER").upper())


def sold_quality_report(session: Session) -> dict[str, Any]:
    rows = session.scalars(select(SoldEvidence)).all()
    cache_rows = session.scalars(select(SoldQueryCache)).all()
    cache_by_product = defaultdict(list)
    for row in cache_rows:
        cache_by_product[row.canonical_product_id].append(row)
    by_model: dict[str, dict[str, Any]] = {}
    for body in CAMERA_BODIES:
        tickets = [r for r in rows if r.canonical_product_id == body.canonical_id]
        accepted = [r for r in tickets if (r.extras or {}).get("accepted_for_valuation") is not False]
        rejected = [r for r in tickets if (r.extras or {}).get("accepted_for_valuation") is False]
        breakdown: Counter[str] = Counter()
        for rec in rejected:
            extras = rec.extras or {}
            breakdown[_code(str(extras.get("rejection_reason") or ""))] += 1
        false_accepts: list[dict[str, Any]] = []
        for rec in accepted:
            title = str((rec.extras or {}).get("title") or "")
            verdict = validate_camera_sold(target=body, sold_title=title)
            if title and not verdict.accepted:
                false_accepts.append(
                    {
                        "title": title,
                        "url": rec.url_or_reference,
                        "reason": verdict.reason,
                        "price": str(rec.sold_price),
                    }
                )
        cache = cache_by_product.get(body.canonical_id) or []
        raw_from_cache = sum(int(c.raw_count or 0) for c in cache)
        by_model[body.canonical_id] = {
            "model": body.model,
            "mpn": body.mpn,
            "raw": raw_from_cache or len(tickets),
            "accepted": len(accepted),
            "rejected": len(rejected),
            "rejection_breakdown": dict(breakdown),
            "best_offer_upper_bound": sum(
                1 for r in tickets if (r.extras or {}).get("best_offer_accepted")
            ),
            "matcher_false_accept_count": len(false_accepts),
            "matcher_false_accepts": false_accepts[:20],
            "sample_accepted_titles": [
                {
                    "title": (r.extras or {}).get("title"),
                    "url": r.url_or_reference,
                    "price": str(r.sold_price),
                    "currency": r.currency,
                    "territory": r.territory,
                    "sold_date": r.sold_date.isoformat() if r.sold_date else None,
                    "price_certainty": (r.extras or {}).get("price_certainty"),
                }
                for r in accepted[:25]
            ],
        }
    precision = measure_identity_precision()
    return {
        "models": by_model,
        "identity_precision": precision,
        "totals": {
            "rows": len(rows),
            "accepted": sum(m["accepted"] for m in by_model.values()),
            "rejected": sum(m["rejected"] for m in by_model.values()),
            "matcher_false_accepts": sum(m["matcher_false_accept_count"] for m in by_model.values()),
        },
    }
