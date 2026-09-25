"""Owner audit of stored Autoza observations. Empty when no database is configured."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app.domains.vehicles.ingest.autoza import autoza_health

FRESH_AFTER = timedelta(days=14)


def _empty() -> dict[str, object]:
    health = autoza_health()
    return {
        "available": False,
        "total_observations": 0,
        "active_vehicles": 0,
        "families": [],
        "latest_refresh": health.get("last_success_at"),
        "rows": [],
        "source": health,
        "fresh": False,
    }


def display_health(stored: dict[str, object] | None, *, now: datetime | None = None) -> dict[str, object]:
    """LIVE, DEGRADED, or DOWN from the last recorded refresh. A stale success is DEGRADED."""

    moment = now or datetime.now(timezone.utc)
    health = dict(stored or autoza_health())
    status = str(health.get("status") or "NOT_RUN")
    last = health.get("last_success_at")
    parsed = _parse(last)
    if status == "DOWN":
        health["fresh"] = False
        return health
    if parsed is None:
        health["status"] = status if status in {"DEGRADED", "LIVE", "NOT_RUN"} else "DOWN"
        health["fresh"] = False
        return health
    age = moment - parsed
    health["fresh"] = age <= FRESH_AFTER
    if age > FRESH_AFTER:
        health["status"] = "DEGRADED"
        health["stale_reason"] = "last successful Autoza refresh is older than 14 days"
    return health


def stored_source_health() -> dict[str, object] | None:
    from app.core.config import get_settings

    if not get_settings().database_url and not __import__("os").environ.get("DATABASE_URL"):
        return None
    try:
        from app.db.session import get_session_factory
        from app.domains.vehicles.orm import CvSourceStateRow

        session = get_session_factory()()
    except Exception:
        return None
    try:
        state = session.get(CvSourceStateRow, "autoza")
    except Exception:
        session.rollback()
        return None
    finally:
        session.close()
    if state is None:
        return None
    return {
        "status": state.status,
        "last_success_at": state.last_success_at.isoformat() if state.last_success_at else None,
        "last_error": state.last_error,
        **(state.payload or {}),
    }


def market_audit(family: str | None = None) -> dict[str, object]:
    from app.core.config import get_settings

    if not get_settings().database_url and not __import__("os").environ.get("DATABASE_URL"):
        return _empty()
    try:
        from app.db.session import get_session_factory
        from app.domains.vehicles.orm import CvMarketObservationRow, CvSourceStateRow

        session = get_session_factory()()
    except Exception:
        return _empty()
    try:
        total = session.query(CvMarketObservationRow).count()
        rows = (
            session.query(CvMarketObservationRow)
            .order_by(CvMarketObservationRow.observed_at.desc())
            .limit(5000)
            .all()
        )
        state = session.get(CvSourceStateRow, "autoza")
    except Exception:
        session.rollback()
        return _empty()
    finally:
        session.close()
    assembled = _assemble(rows, state, family)
    assembled["total_observations"] = total
    return assembled


def _assemble(rows, state, family: str | None) -> dict[str, object]:
    by_listing: dict[str, list] = defaultdict(list)
    for row in rows:
        by_listing[row.listing_id].append(row)
    active = []
    families: dict[str, int] = defaultdict(int)
    for listing_rows in by_listing.values():
        ordered = sorted(listing_rows, key=lambda item: item.observed_at)
        latest = ordered[-1]
        if latest.status == "DISAPPEARED":
            continue
        families[latest.model_family] += 1
        if family and latest.model_family != family:
            continue
        payload = latest.payload or {}
        active.append(
            {
                "vehicle": f"{payload.get('manufacturer') or ''} {latest.model_family}".strip(),
                "family": latest.model_family,
                "year": payload.get("year"),
                "mileage_km": payload.get("mileage_km"),
                "price_eur": payload.get("asking_price_eur"),
                "vat_basis": payload.get("vat_classification") or "UNKNOWN",
                "location": payload.get("location") or "",
                "source": latest.source,
                "first_seen": ordered[0].observed_at.isoformat(),
                "last_seen": latest.observed_at.isoformat(),
            }
        )
    stored = None
    if state is not None:
        stored = {
            "status": state.status,
            "last_success_at": state.last_success_at.isoformat() if state.last_success_at else None,
            "last_error": state.last_error,
            **(state.payload or {}),
        }
    health = display_health(stored)
    return {
        "available": True,
        "total_observations": len(rows) if not family else len(rows),
        "active_vehicles": len(active),
        "families": [{"family": name, "active": count} for name, count in sorted(families.items())],
        "latest_refresh": health.get("last_success_at"),
        "rows": active[:200],
        "source": health,
        "fresh": bool(health.get("fresh")),
    }


def _parse(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
