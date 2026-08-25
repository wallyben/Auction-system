"""Health snapshot for the eBay notification endpoint (does not claim eBay subscription)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.privacy.ebay_signature import signature_verifier_ready
from app.privacy.identifiers import token_is_valid


def notification_health(session: Session | None = None) -> dict[str, Any]:
    current = get_settings()
    token = (getattr(current, "ebay_notification_verification_token", None) or "").strip()
    endpoint = (getattr(current, "ebay_notification_endpoint_url", None) or "").strip()
    token_ok = token_is_valid(token)
    endpoint_ok = endpoint.startswith("https://")
    db = "skipped"
    if session is not None:
        try:
            session.execute(select(1))
            db = "up"
        except Exception:  # noqa: BLE001
            db = "down"
    ready = token_ok and endpoint_ok and signature_verifier_ready() and db != "down"
    return {
        "ready": ready,
        "ready_for_ebay_challenge": token_ok and endpoint_ok,
        "endpoint_configured": bool(endpoint),
        "endpoint_https": endpoint_ok,
        "verification_token_configured": bool(token),
        "verification_token_length": len(token) if token else 0,
        "verification_token_valid": token_ok,
        "database": db,
        "processor": "ready" if db != "down" else "database_unavailable",
        "signature_verifier": "ready" if signature_verifier_ready() else "unavailable",
        "ebay_subscription_active": False,
        "note": (
            "ARIE does not claim the eBay notification subscription is active. "
            "Confirm verification in the eBay Developer portal, then run make ebay-check."
        ),
    }


notification_health = notification_health
