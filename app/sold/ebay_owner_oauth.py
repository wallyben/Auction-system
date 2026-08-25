"""Owner eBay user-OAuth for owner-only sold orders (Sell Fulfillment).

This cannot enable a disabled Production keyset. It only reads the owner's own
orders after consent. Active Browse listings are never labelled as sold.

Owner steps (password is never collected by ARIE):
  1. In the eBay Developer Portal, Production app → User tokens → create a RuName.
  2. Set the Auth Accepted URL to the production callback:
     https://auction-system-l6je.onrender.com/oauth/ebay/callback
  3. Set EBAY_RU_NAME to that RuName (the authorize redirect_uri value IS the RuName).
  4. Optionally set EBAY_OAUTH_REDIRECT_URI to the same callback URL.
  5. Open GET /oauth/ebay/start (or the URL from GET /oauth/ebay/status).
  6. Sign in to eBay and approve sell.fulfillment.readonly.
  7. ARIE stores the refresh token in Postgres and ingests sold orders.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings, settings
from app.identity.resolvers import identify_with_resolvers
from app.models.enums import EvidenceType
from app.sold.persist import persist_sold_hits
from app.sold.provider import SoldEvidenceHit
from app.sold.token_store import (
    load_ebay_refresh_token,
    load_oauth_state,
    save_ebay_tokens,
    save_oauth_state,
    token_status,
)

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
PRODUCTION_CALLBACK = "https://auction-system-l6je.onrender.com/oauth/ebay/callback"
_STATE_PATH = Path("artifacts/runtime/ebay_oauth_state.txt")


def _callback_url() -> str:
    current = get_settings()
    return (getattr(current, "ebay_oauth_redirect_uri", None) or "").strip() or PRODUCTION_CALLBACK


def _ru_name() -> str:
    return (getattr(get_settings(), "ebay_ru_name", None) or "").strip()


def consent_status(session: Session | None = None) -> dict[str, Any]:
    current = get_settings()
    ru = _ru_name()
    redirect = _callback_url()
    tokens = token_status(session)
    refresh = load_ebay_refresh_token(session)
    steps = [
        "Open the eBay Developer Portal for the Production ARIE application.",
        "Create a RuName whose Auth Accepted URL is " + redirect + ".",
        "Set EBAY_RU_NAME to that RuName (this value is the OAuth redirect_uri parameter).",
        "Set EBAY_OAUTH_REDIRECT_URI=" + redirect + " if it is not already the default.",
        "Open GET /oauth/ebay/start on the live host (or the consent_url below).",
        "Sign in to eBay and click Agree. ARIE never asks for the eBay password.",
        "The callback stores the refresh token in Postgres and ingests owner sold orders.",
    ]
    return {
        "configured_client": bool(current.ebay_client_id and current.ebay_client_secret),
        "ru_name_configured": bool(ru),
        "redirect_uri": redirect,
        "redirect_uri_configured": bool(redirect),
        "refresh_token_configured": bool(refresh),
        "scope": OWNER_SOLD_SCOPE,
        "official_docs": "https://developer.ebay.com/api-docs/static/oauth-authorization-code-grant.html",
        "orders_docs": "https://developer.ebay.com/api-docs/sell/fulfillment/resources/order/methods/getOrders",
        "owner_steps": steps,
        "owner_action": None if refresh else "Open consent_url, sign in to eBay, and approve. Then ARIE ingests sold orders.",
        "secrets_included": False,
        **tokens,
    }


def start_consent(session: Session | None = None) -> dict[str, Any]:
    current = get_settings()
    status = consent_status(session)
    ru = _ru_name()
    if not current.ebay_client_id or not ru:
        return {**status, "url": None, "consent_url": None, "ok": False}
    state = secrets.token_urlsafe(24)
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(state, encoding="utf-8")
    if session is not None:
        save_oauth_state(session, state)
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
    return {**status, "url": url, "consent_url": url, "ok": True, "state_configured": True}


async def exchange_code(code: str, state: str, session: Session | None = None) -> dict[str, Any]:
    expected_file = _STATE_PATH.read_text(encoding="utf-8").strip() if _STATE_PATH.exists() else ""
    expected_db = load_oauth_state(session)
    expected = expected_db or expected_file
    if not expected or not state or state != expected:
        return {"ok": False, "error": "invalid_state"}
    current = get_settings()
    ru = _ru_name()
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
    if session is not None:
        save_ebay_tokens(
            session,
            refresh_token=str(refresh),
            access_token=str(payload.get("access_token") or "") or None,
            scope=str(payload.get("refresh_token_expires_in") and OWNER_SOLD_SCOPE or OWNER_SOLD_SCOPE),
            token_type=str(payload.get("token_type") or "User Access Token"),
            expires_in=int(payload.get("expires_in") or 7200),
            extras={"grant": "authorization_code"},
        )
    else:
        from app.privacy.ebay_challenge import upsert_env_key

        upsert_env_key("EBAY_REFRESH_TOKEN", str(refresh))
        get_settings.cache_clear()
    ingested = {"imported": 0, "duplicates": 0}
    if session is not None:
        ingested = await ingest_owner_orders(session, limit=50)
    return {
        "ok": True,
        "http_status": 200,
        "refresh_token_stored": True,
        "stored_in_database": session is not None,
        "orders_ingested": ingested,
        "secrets_included": False,
    }


def _money(block: dict[str, Any] | None) -> tuple[Decimal | None, str]:
    if not isinstance(block, dict) or block.get("value") in (None, ""):
        return None, "EUR"
    try:
        return Decimal(str(block.get("value"))), str(block.get("currency") or "EUR")
    except Exception:
        return None, str(block.get("currency") or "EUR")


def _parse_orders(payload: dict[str, Any], *, market: str) -> list[SoldEvidenceHit]:
    hits: list[SoldEvidenceHit] = []
    for order in payload.get("orders") or []:
        if not isinstance(order, dict):
            continue
        created = order.get("creationDate") or datetime.now(timezone.utc).isoformat()
        try:
            sold_at = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        except ValueError:
            sold_at = datetime.now(timezone.utc)
        ship_total, _ship_cur = _money(((order.get("pricingSummary") or {}).get("deliveryCost")))
        fulfillment = (order.get("fulfillmentStartInstructions") or [{}])[0]
        ship_to = ((fulfillment.get("shippingStep") or {}).get("shipTo") or {}).get("contactAddress") or {}
        territory = str(ship_to.get("countryCode") or market or "IE")[:8]
        for item in order.get("lineItems") or []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            price, currency = _money(item.get("lineItemCost") or item.get("total") or {})
            if price is None:
                price, currency = _money(((order.get("pricingSummary") or {}).get("total")))
            if price is None or price <= 0:
                continue
            identity = identify_with_resolvers(title=title)
            condition = str(item.get("soldFormat") or "")
            hits.append(
                SoldEvidenceHit(
                    source="ebay_owner_fulfillment",
                    title=title,
                    sold_price_eur=price,
                    territory=territory,
                    condition=condition or "unknown",
                    channel="ebay_owner_sold",
                    sold_date=sold_at,
                    evidence_type=EvidenceType.REALISED_SALE,
                    quality="high",
                    url=None,
                    notes="Owner eBay Fulfillment line item after user OAuth. Not a Browse listing.",
                    variant=identity.variant or "",
                    currency=currency,
                    shipping=ship_total,
                    identity_key=identity.canonical_key,
                    provenance=f"fulfillment:{order.get('orderId')}:{item.get('lineItemId')}",
                    market=territory,
                )
            )
    return hits


async def ingest_owner_orders(session: Session, *, limit: int = 50) -> dict[str, Any]:
    refresh = load_ebay_refresh_token(session)
    if not refresh:
        return {"imported": 0, "duplicates": 0, "ok": False, "error": "no_refresh_token"}
    token = await _refresh_user_token(refresh)
    if not token:
        return {"imported": 0, "duplicates": 0, "ok": False, "error": "refresh_failed"}
    env = settings.ebay_api_env
    params = {"limit": str(min(limit, 200))}
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(ORDERS_URL[env], params={**params, "filter": "orderfulfillmentstatus:{FULFILLED|IN_PROGRESS}"}, headers=headers)
        if response.status_code == 400:
            response = await client.get(ORDERS_URL[env], params=params, headers=headers)
    if response.status_code != 200:
        return {
            "imported": 0,
            "duplicates": 0,
            "ok": False,
            "http_status": response.status_code,
            "error": "fulfillment_http_error",
        }
    hits = _parse_orders(response.json() or {}, market="IE")
    stats = persist_sold_hits(session, hits)
    stats["ok"] = True
    stats["orders_seen"] = len((response.json() or {}).get("orders") or [])
    stats["line_items"] = len(hits)
    return stats


class EbayOwnerOrdersProvider:
    """Owner-only realised sales after user consent. Never uses Browse asking prices."""

    name = "ebay_owner_fulfillment"
    classification = "REALIZED_SOLD"

    async def healthcheck(self) -> dict[str, object]:
        status = consent_status()
        refresh = load_ebay_refresh_token()
        if not refresh:
            return {
                "provider": self.name,
                "ok": False,
                "available": False,
                "classification": self.classification,
                "note": status.get("owner_action"),
                "owner_steps": status.get("owner_steps"),
            }
        token = await _refresh_user_token(refresh)
        if not token:
            return {
                "provider": self.name,
                "ok": False,
                "available": False,
                "classification": self.classification,
                "note": "Refresh token present but user-token exchange failed. Re-run consent.",
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
        # Live Fulfillment calls belong in ingest_owner_orders, which persists SoldEvidence.
        # Search is DB-backed via IrishPanelProvider so we do not hammer the orders API.
        return []

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
