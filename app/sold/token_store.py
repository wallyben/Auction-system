"""Load and persist eBay user-OAuth tokens. Prefer Postgres over .env."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.oauth import OAuthCredential
from app.sold.crypto import decrypt_secret, encrypt_secret

EBAY_PROVIDER = "ebay"
EBAY_STATE_PROVIDER = "ebay_oauth_csrf"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_ebay_refresh_token(session: Session | None = None) -> str:
    if session is not None:
        row = session.scalar(select(OAuthCredential).where(OAuthCredential.provider == EBAY_PROVIDER))
        if row and (row.refresh_token or "").strip():
            plain = decrypt_secret(row.refresh_token.strip())
            return (plain or "").strip()
    return (getattr(get_settings(), "ebay_refresh_token", None) or "").strip()


def save_ebay_tokens(
    session: Session,
    *,
    refresh_token: str,
    access_token: str | None = None,
    scope: str | None = None,
    token_type: str | None = None,
    expires_in: int | None = None,
    extras: dict[str, Any] | None = None,
) -> None:
    row = session.scalar(select(OAuthCredential).where(OAuthCredential.provider == EBAY_PROVIDER))
    expires_at = None
    if expires_in:
        expires_at = _utcnow() + timedelta(seconds=int(expires_in))
    payload = extras or {}
    payload["stored_at"] = _utcnow().isoformat()
    if row is None:
        row = OAuthCredential(provider=EBAY_PROVIDER, extras={})
        session.add(row)
    row.refresh_token = encrypt_secret(refresh_token)
    if access_token:
        row.access_token = encrypt_secret(access_token)
    if scope:
        row.scope = scope
    if token_type:
        row.token_type = token_type
    if expires_at is not None:
        row.expires_at = expires_at
    merged = dict(row.extras or {})
    merged.update(payload)
    merged["encrypted"] = True
    row.extras = merged
    session.flush()


def record_oauth_event(session: Session, **fields: Any) -> None:
    row = session.scalar(select(OAuthCredential).where(OAuthCredential.provider == EBAY_PROVIDER))
    if row is None:
        return
    merged = dict(row.extras or {})
    merged.update({k: v for k, v in fields.items() if v is not None})
    row.extras = merged
    session.flush()


def save_oauth_state(session: Session, state: str) -> None:
    row = session.scalar(select(OAuthCredential).where(OAuthCredential.provider == EBAY_STATE_PROVIDER))
    if row is None:
        row = OAuthCredential(provider=EBAY_STATE_PROVIDER, extras={})
        session.add(row)
    row.extras = {"state": state, "created_at": _utcnow().isoformat()}
    session.flush()


def load_oauth_state(session: Session | None) -> str:
    if session is None:
        return ""
    row = session.scalar(select(OAuthCredential).where(OAuthCredential.provider == EBAY_STATE_PROVIDER))
    if not row:
        return ""
    return str((row.extras or {}).get("state") or "")


def token_status(session: Session | None = None) -> dict[str, Any]:
    refresh = load_ebay_refresh_token(session)
    db_row = None
    extras: dict[str, Any] = {}
    if session is not None:
        db_row = session.scalar(select(OAuthCredential).where(OAuthCredential.provider == EBAY_PROVIDER))
        extras = dict((db_row.extras or {}) if db_row else {})
    revoked = extras.get("token_revoked") is True or extras.get("last_error") == "invalid_grant"
    scope = (db_row.scope if db_row else None) or extras.get("scope")
    return {
        "owner_oauth_connected": bool(refresh) and not revoked,
        "scope_valid": bool(scope) and "sell.fulfillment.readonly" in str(scope) and not revoked,
        "refresh_token_configured": bool(refresh),
        "refresh_token_in_database": bool(db_row and (db_row.refresh_token or "").strip()),
        "tokens_encrypted": bool(extras.get("encrypted")),
        "scope": scope,
        "last_refresh_at": extras.get("last_refresh_at"),
        "last_sold_ingest_at": extras.get("last_sold_ingest_at"),
        "last_ingest_count": extras.get("last_ingest_count"),
        "last_error": extras.get("last_error") if extras.get("last_error") not in {None, ""} else None,
        "token_revoked": revoked,
        "updated_at": db_row.updated_at.isoformat() if db_row and db_row.updated_at else None,
        "secrets_included": False,
    }
