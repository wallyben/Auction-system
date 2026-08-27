"""Product-level sold query cache. One CompSniper call serves every matching listing."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.orm import SoldQueryCache

HOT_TTL_HOURS_DEFAULT = 18
SLOW_TTL_HOURS_DEFAULT = 60


def cache_key(
    canonical_product_id: str,
    variant: str,
    marketplace: str,
    condition_bucket: str,
) -> str:
    raw = "|".join(
        [
            (canonical_product_id or "").lower(),
            (variant or "body").lower(),
            (marketplace or "GB").upper(),
            (condition_bucket or "used").lower(),
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ttl_hours(*, accepted_count: int, sales_30d: int = 0) -> int:
    hot = int(getattr(settings, "compsniper_hot_ttl_hours", HOT_TTL_HOURS_DEFAULT) or HOT_TTL_HOURS_DEFAULT)
    slow = int(getattr(settings, "compsniper_slow_ttl_hours", SLOW_TTL_HOURS_DEFAULT) or SLOW_TTL_HOURS_DEFAULT)
    if accepted_count >= 8 or sales_30d >= 5:
        return hot
    return slow


def get_cache(
    session: Session,
    *,
    canonical_product_id: str,
    variant: str = "body",
    marketplace: str = "GB",
    condition_bucket: str = "used",
) -> SoldQueryCache | None:
    key = cache_key(canonical_product_id, variant, marketplace, condition_bucket)
    return session.scalar(select(SoldQueryCache).where(SoldQueryCache.cache_key == key))


def cache_is_fresh(row: SoldQueryCache | None, *, now: datetime | None = None) -> bool:
    """True when we must not spend another paid request (TTL still running)."""
    if row is None or row.queried_at is None:
        return False
    now = now or _now()
    queried = row.queried_at
    if queried.tzinfo is None:
        queried = queried.replace(tzinfo=timezone.utc)
    age = now - queried
    ttl = timedelta(hours=int(row.ttl_hours or SLOW_TTL_HOURS_DEFAULT))
    return age <= ttl


def cache_is_successful(row: SoldQueryCache | None, *, now: datetime | None = None) -> bool:
    """True when cached evidence may be used for BUY_READY freshness."""
    if not cache_is_fresh(row, now=now):
        return False
    status = getattr(row, "last_http_status", None)
    if status != 200:
        return False
    extras = getattr(row, "extras", None) or {}
    if extras.get("error") or extras.get("code") in {"quota_exceeded", "rate_limited", "unauthorized", "network"}:
        return False
    return True


def upsert_cache(
    session: Session,
    *,
    canonical_product_id: str,
    variant: str,
    marketplace: str,
    condition_bucket: str,
    keyword: str,
    raw_count: int,
    accepted_count: int,
    rejected_count: int,
    last_http_status: int | None,
    quota_remaining: int | None,
    extras: dict[str, Any] | None = None,
    sales_30d: int = 0,
) -> SoldQueryCache:
    key = cache_key(canonical_product_id, variant, marketplace, condition_bucket)
    row = session.scalar(select(SoldQueryCache).where(SoldQueryCache.cache_key == key))
    hours = ttl_hours(accepted_count=accepted_count, sales_30d=sales_30d)
    payload = dict(
        canonical_product_id=canonical_product_id,
        variant=variant,
        marketplace=marketplace,
        condition_bucket=condition_bucket,
        keyword=keyword,
        queried_at=_now(),
        raw_count=raw_count,
        accepted_count=accepted_count,
        rejected_count=rejected_count,
        last_http_status=last_http_status,
        quota_remaining=quota_remaining,
        ttl_hours=hours,
        extras=extras or {},
    )
    if row is None:
        row = SoldQueryCache(cache_key=key, **payload)
        session.add(row)
    else:
        for name, value in payload.items():
            setattr(row, name, value)
    session.flush()
    return row


def cache_stats(session: Session) -> dict[str, Any]:
    rows = session.scalars(select(SoldQueryCache)).all()
    fresh = sum(1 for row in rows if cache_is_fresh(row))
    return {
        "entries": len(rows),
        "fresh": fresh,
        "stale": len(rows) - fresh,
        "products": len({row.canonical_product_id for row in rows}),
        "accepted_total": int(sum(row.accepted_count or 0 for row in rows)),
    }
