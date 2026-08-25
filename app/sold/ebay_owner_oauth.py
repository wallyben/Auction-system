"""Owner eBay user-OAuth for owner-only sold orders (Sell Fulfillment).

This is not a way to enable a disabled Production keyset. It cannot run until
the keyset is enabled and a RuName/redirect URI exist in the Developer Portal.
Active Browse listings are never labelled as sold.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings, settings
from app.models.enums import EvidenceType
from app.privacy.ebay_challenge import upsert_env_key
from app.sold.provider import SoldEvidenceHit

AUTHORIZE_URL = {
    "production": "https://auth.ebay.com/oauth2/authorize",
    "sandbox": "https://auth.sandbox.ebay.com/oauth2/authorize",
}
TOKEN_URL = {
    "production": "https://api.ebay.com/identity/v1/oauth2/token",
    "sandbox": "https://api.sandbox.ebay.com/identity/v1/oauth2/token",
}
ORDERS_URL = {
    "production": "https://api.ebay.com/sell/fulfillment/v1/order",
    "sandbox": "https://api.sandbox.ebay.com/sell/fulfillment/v1/order",
}
OWNER_SOLD_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly"
_STATE_PATH = Path("artifacts/runtime/ebay_oauth_state.txt")


def consent_status() -> dict[str, Any]:
    current = get_settings()
    ru = (getattr(current, "ebay_ru_name", None) or "").strip()
    redirect = (getattr(current, "ebay_oauth_redirect_uri", None) or "").strip()
    refresh = (getattr(current, "ebay_refresh_token", None) or "").strip()
    return {
        "configured_client": bool(current.ebay_client_id and current.ebay_client_secret),
        "ru_name_configured": bool(ru),
        "redirect_uri_configured": bool(redirect),
        "refresh_token_configured": bool(refresh),
        "scope": OWNER_SOLD_SCOPE,
        "owner_action": (
            None
            if refresh
            else (
                "Create a RuName (redirect URI) on the Production application after the "
                "keyset is enabled, set EBAY_RU_NAME and EBAY_OAUTH_REDIRECT_URI, then open "
                "`make ebay-owner-oauth-url` and grant consent. Do not regenerate keys."
            )
        ),
        "secrets_included": False,
    }


def start_consent() -> dict[str, Any]:
    current = get_settings()
    status = consent_status()
    ru = (getattr(current, "ebay_ru_name", None) or "").strip()
    if not current.ebay_client_id or not ru:
        return {**status, "url": None, "ok": False}
    state = secrets.token_urlsafe(24)
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(state, encoding="utf-8")
    query = urlencode(
        {
            "client_id": current.ebay_client_id,
            "redirect_uri": ru,
            "response_type": "code",
            "scope": OWNER_SOLD_SCOPE,
            "state": state,
        }
    )
    url = f"{AUTHORIZE_URL[current.ebay_api_env]}?{query}"
    return {**status, "url": url, "ok": True, "state_configured": True}


async def exchange_code(code: str, state: str) -> dict[str, Any]:
    expected = _STATE_PATH.read_text(encoding="utf-8").strip() if _STATE_PATH.exists() else ""
    if not expected or not state or state != expected:
        return {"ok": False, "error": "invalid_state"}
    current = get_settings()
    ru = (getattr(current, "ebay_ru_name", None) or "").strip()
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            TOKEN_URL[current.ebay_api_env],
            auth=(current.ebay_client_id, current.ebay_client_secret),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": ru,
            },
        )
    if response.status_code != 200:
        return {"ok": False, "http_status": response.status_code, "error": "oauth_exchange_failed"}
    payload = response.json()
    refresh = payload.get("refresh_token")
    if not refresh:
        return {"ok": False, "error": "missing_refresh_token"}
    upsert_env_key("EBAY_REFRESH_TOKEN", str(refresh))
    get_settings.cache_clear()
    return {"ok": True, "http_status": 200, "refresh_token_stored": True, "secrets_included": False}


class EbayOwnerOrdersProvider:
    """Owner-only realised sales after user consent. Never uses Browse asking prices."""

    name = "ebay_owner_fulfillment"
    classification = "REALIZED_SOLD"

    async def healthcheck(self) -> dict[str, object]:
        status = consent_status()
        refresh = (getattr(get_settings(), "ebay_refresh_token", None) or "").strip()
        if not refresh:
            return {
                "provider": self.name,
                "ok": False,
                "available": False,
                "classification": self.classification,
                "note": status.get("owner_action"),
            }
        token = await _refresh_user_token(refresh)
        if not token:
            return {
                "provider": self.name,
                "ok": False,
                "available": False,
                "classification": self.classification,
                "note": "Refresh token present but user-token exchange failed.",
            }
        env = settings.ebay_api_env
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                ORDERS_URL[env],
                params={"limit": "1"},
                headers={"Authorization": f"Bearer {token}"},
            )
        return {
            "provider": self.name,
            "ok": response.status_code == 200,
            "available": response.status_code == 200,
            "http_status": response.status_code,
            "classification": self.classification,
            "note": "Owner-only orders. Not general market sold comps.",
        }

    async def search_realised_sales(
        self, product: str, market: str, condition: str, *, limit: int = 20
    ) -> list[SoldEvidenceHit]:
        refresh = (getattr(get_settings(), "ebay_refresh_token", None) or "").strip()
        if not refresh:
            return []
        token = await _refresh_user_token(refresh)
        if not token:
            return []
        env = settings.ebay_api_env
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                ORDERS_URL[env],
                params={"limit": str(min(limit, 50))},
                headers={"Authorization": f"Bearer {token}"},
            )
        if response.status_code != 200:
            return []
        hits: list[SoldEvidenceHit] = []
        needle = (product or "").lower()[:80]
        for order in (response.json() or {}).get("orders") or []:
            if not isinstance(order, dict):
                continue
            title_parts = []
            for item in order.get("lineItems") or []:
                if isinstance(item, dict):
                    title_parts.append(str(item.get("title") or ""))
            title = " ".join(title_parts).strip() or str(order.get("orderId") or "ebay-order")
            if needle and needle not in title.lower():
                continue
            total = ((order.get("pricingSummary") or {}).get("total") or {}).get("value")
            try:
                price = Decimal(str(total))
            except Exception:
                continue
            created = order.get("creationDate") or datetime.now(timezone.utc).isoformat()
            try:
                sold_at = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            except ValueError:
                sold_at = datetime.now(timezone.utc)
            hits.append(
                SoldEvidenceHit(
                    source=self.name,
                    title=title,
                    sold_price_eur=price,
                    territory=market or "IE",
                    condition=condition or "unknown",
                    channel="ebay_owner_sold",
                    sold_date=sold_at,
                    evidence_type=EvidenceType.REALISED_SALE,
                    quality="high",
                    url=None,
                    notes="Owner eBay Fulfillment order after user OAuth. Not a Browse listing.",
                )
            )
            if len(hits) >= limit:
                break
        return hits

    async def freshness(self) -> datetime | None:
        return None


async def _refresh_user_token(refresh: str) -> str | None:
    current = get_settings()
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            TOKEN_URL[current.ebay_api_env],
            auth=(current.ebay_client_id, current.ebay_client_secret),
            data={"grant_type": "refresh_token", "refresh_token": refresh, "scope": OWNER_SOLD_SCOPE},
        )
    if response.status_code != 200:
        return None
    return str((response.json() or {}).get("access_token") or "") or None
