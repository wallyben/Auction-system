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
    record_oauth_event,
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
PRODUCTION_DECLINED = "https://auction-system-l6je.onrender.com/oauth/ebay/declined"
PRODUCTION_PRIVACY = "https://auction-system-l6je.onrender.com/privacy/ebay"
PORTAL_AUTH_URL = "https://developer.ebay.com/my/auth?env=production&index=0"
OAUTH_DOCS = "https://developer.ebay.com/api-docs/static/oauth-authorization-code-grant.html"
REFRESH_DOCS = "https://developer.ebay.com/api-docs/static/oauth-refresh-token-request.html"
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
    ru_is_url = ru.lower().startswith("http")
    authorize_host = AUTHORIZE_URL[current.ebay_api_env]
    sandbox = current.ebay_api_env == "sandbox"
    portal = {
        "environment": "Production" if not sandbox else "Sandbox",
        "portal_url": PORTAL_AUTH_URL if not sandbox else "https://developer.ebay.com/my/auth?env=sandbox&index=0",
        "display_title": "ARIE owner sold-data",
        "privacy_policy_url": PRODUCTION_PRIVACY,
        "auth_accepted_url": redirect,
        "auth_declined_url": PRODUCTION_DECLINED,
        "render_variable": "EBAY_RU_NAME",
        "render_variable_value": "Paste the RuName identifier eBay shows after Get a RuName — not the https callback URL.",
        "also_set": f"EBAY_OAUTH_REDIRECT_URI={redirect}",
        "note": "The OAuth redirect_uri query parameter is the RuName, not the Auth Accepted URL.",
    }
    steps = [
        "Deploy branch cursor/arie-commercial-readiness-7682 to the Render service auction-system-l6je.",
        f"Open {portal['portal_url']} (Production application, User tokens / Get a RuName).",
        f"Display Title: {portal['display_title']}",
        f"Privacy Policy URL: {portal['privacy_policy_url']}",
        f"Auth Accepted URL: {portal['auth_accepted_url']}",
        f"Auth Declined URL: {portal['auth_declined_url']}",
        "After eBay shows the RuName (YourApp-YourApp-PRD-...), set Render env EBAY_RU_NAME to that exact string and restart the service.",
        "Open https://auction-system-l6je.onrender.com/oauth/ebay/start — sign in to eBay and click Agree. ARIE never asks for the password.",
    ]
    return {
        "configured_client": bool(current.ebay_client_id and current.ebay_client_secret),
        "ru_name_configured": bool(ru),
        "redirect_uri": redirect,
        "redirect_uri_configured": bool(redirect),
        "refresh_token_configured": bool(refresh),
        "scope": OWNER_SOLD_SCOPE,
        "official_docs": OAUTH_DOCS,
        "refresh_docs": REFRESH_DOCS,
        "orders_docs": "https://developer.ebay.com/api-docs/sell/fulfillment/resources/order/methods/getOrders",
        "authorize_host": authorize_host,
        "sandbox_used": sandbox,
        "ru_name_looks_like_url": ru_is_url,
        "portal": portal,
        "owner_steps": steps,
        "owner_action": None if refresh else "Open consent_url, sign in to eBay, and approve. Then ARIE ingests sold orders.",
        "secrets_included": False,
        **tokens,
    }


def start_consent(session: Session | None = None) -> dict[str, Any]:
    current = get_settings()
    status = consent_status(session)
    ru = _ru_name()
    sandbox = current.ebay_api_env == "sandbox"
    ru_is_url = bool(ru) and ru.lower().startswith("http")
    if not current.ebay_client_id or not ru or ru_is_url or sandbox:
        reason = "missing_ebay_ru_name"
        if sandbox:
            reason = "sandbox_blocked"
        elif ru_is_url:
            reason = "ru_name_must_be_identifier_not_url"
        elif not current.ebay_client_id:
            reason = "missing_ebay_client_id"
        elif not ru:
            reason = "missing_ebay_ru_name"
        return {**status, "url": None, "consent_url": None, "ok": False, "error": reason}
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
    if session is None:
        return {"ok": False, "error": "database_required_for_token_persistence", "secrets_included": False}
    save_ebay_tokens(
        session,
        refresh_token=str(refresh),
        access_token=str(payload.get("access_token") or "") or None,
        scope=OWNER_SOLD_SCOPE,
        token_type=str(payload.get("token_type") or "User Access Token"),
        expires_in=int(payload.get("expires_in") or 7200),
        extras={
            "grant": "authorization_code",
            "refresh_token_expires_in": payload.get("refresh_token_expires_in"),
            "token_revoked": False,
            "last_error": None,
        },
    )
    ingested = await ingest_owner_orders(session, limit=50)
    return {
        "ok": True,
        "http_status": 200,
        "refresh_token_stored": True,
        "stored_in_database": True,
        "tokens_encrypted": True,
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


def _cancelled(order: dict[str, Any]) -> bool:
    cancel = order.get("cancelStatus") or {}
    state = str(cancel.get("cancelState") or "").upper()
    if state in {"CANCELED", "CANCELLED"}:
        return True
    status = str(order.get("orderFulfillmentStatus") or "").upper()
    return status in {"CANCELLED", "CANCELED"}


def _line_refunded(order: dict[str, Any], item: dict[str, Any]) -> bool:
    if item.get("refunds") or item.get("refunded"):
        return True
    payments = order.get("paymentSummary") or {}
    if payments.get("refunds"):
        return True
    blob = f"{item.get('lineItemFulfillmentStatus') or ''} {order.get('orderPaymentStatus') or ''}".lower()
    return "refund" in blob


def _parse_orders(payload: dict[str, Any], *, market: str) -> list[SoldEvidenceHit]:
    hits: list[SoldEvidenceHit] = []
    for order in payload.get("orders") or []:
        if not isinstance(order, dict):
            continue
        if _cancelled(order):
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
            if _line_refunded(order, item):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            price, currency = _money(item.get("lineItemCost") or item.get("total") or {})
            if price is None:
                price, currency = _money(((order.get("pricingSummary") or {}).get("total")))
            if price is None or price <= 0:
                continue
            try:
                qty = int(item.get("quantity") or 1)
            except (TypeError, ValueError):
                qty = 1
            if qty <= 0:
                continue
            identity = identify_with_resolvers(title=title)
            condition = str(item.get("soldFormat") or item.get("itemCondition") or "")
            hits.append(
                SoldEvidenceHit(
                    source="ebay_owner_orders",
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
                    quantity=qty,
                    identity_confidence=identity.confidence,
                    matching_confidence=identity.confidence,
                )
            )
    return hits


async def ingest_owner_orders(session: Session, *, limit: int = 50) -> dict[str, Any]:
    refresh = load_ebay_refresh_token(session)
    if not refresh:
        return {"imported": 0, "duplicates": 0, "ok": False, "error": "no_refresh_token"}
    token = await _refresh_user_token(refresh, session)
    if not token:
        st = token_status(session)
        if st.get("token_revoked"):
            return {
                "imported": 0,
                "duplicates": 0,
                "ok": False,
                "error": "owner_token_revoked",
                "message": "invalid_grant: owner must re-consent. Empty ingest is not a market-sold panel.",
            }
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
    payload = response.json() or {}
    hits = _parse_orders(payload, market="IE")
    stats = persist_sold_hits(session, hits)
    stats["ok"] = True
    stats["orders_seen"] = len(payload.get("orders") or [])
    stats["line_items"] = len(hits)
    stats["empty_orders_is_not_no_market"] = True
    if stats["orders_seen"] == 0:
        stats["note"] = "Zero owner orders is not a general sold-comp panel. Do not infer market prices."
    record_oauth_event(
        session,
        last_sold_ingest_at=datetime.now(timezone.utc).isoformat(),
        last_ingest_count=stats.get("imported", 0),
        last_error=None,
    )
    return stats


class EbayOwnerOrdersProvider:
    """Owner-only realised sales after user consent. Never uses Browse asking prices."""

    name = "ebay_owner_orders"
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
        token = await _refresh_user_token(refresh, None)
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


async def _refresh_user_token(refresh: str, session: Session | None = None) -> str | None:
    current = get_settings()
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            TOKEN_URL[current.ebay_api_env],
            auth=(current.ebay_client_id, current.ebay_client_secret),
            data={"grant_type": "refresh_token", "refresh_token": refresh, "scope": OWNER_SOLD_SCOPE},
        )
    body = ""
    try:
        body = response.text[:400]
    except Exception:
        body = ""
    if response.status_code != 200:
        revoked = "invalid_grant" in body.lower() or response.status_code in {400, 401}
        if session is not None:
            record_oauth_event(
                session,
                last_error="invalid_grant" if revoked else "refresh_failed",
                token_revoked=revoked,
                last_refresh_http_status=response.status_code,
            )
        return None
    access = str((response.json() or {}).get("access_token") or "") or None
    if session is not None:
        record_oauth_event(
            session,
            last_refresh_at=datetime.now(timezone.utc).isoformat(),
            last_error=None,
            token_revoked=False,
            last_refresh_http_status=200,
        )
    return access
