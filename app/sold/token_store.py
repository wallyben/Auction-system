"""Load and persist eBay user-OAuth tokens. Prefer Postgres over .env."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.oauth import OAuthCredential
from app.privacy.ebay_challenge import upsert_env_key

EBAY_PROVIDER = "ebay"
EBAY_STATE_PROVIDER = "ebay_oauth_csrf"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_ebay_refresh_token(session: Session | None = None) -> str:
    if session is not None:
        row = session.scalar(select(OAuthCredential).where(OAuthCredential.provider == EBAY_PROVIDER))
        if row and (row.refresh_token or "").strip():
            return row.refresh_token.strip()
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
    row.refresh_token = refresh_token
    if access_token:
        row.access_token = access_token
    if scope:
        row.scope = scope
    if token_type:
        row.token_type = token_type
    if expires_at is not None:
        row.expires_at = expires_at
    merged = dict(row.extras or {})
    merged.update(payload)
    row.extras = merged
    # Best-effort local .env mirror for CLI/dev. Render disk is ephemeral; DB is source of truth.
    try:
        upsert_env_key("EBAY_REFRESH_TOKEN", refresh_token)
    except Exception:
        pass
    get_settings.cache_clear()
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
    if session is not None:
        db_row = session.scalar(select(OAuthCredential).where(OAuthCredential.provider == EBAY_PROVIDER))
    return {
        "refresh_token_configured": bool(refresh),
        "refresh_token_in_database": bool(db_row and (db_row.refresh_token or "").strip()),
        "scope": (db_row.scope if db_row else None) or None,
        "updated_at": db_row.updated_at.isoformat() if db_row and db_row.updated_at else None,
        "secrets_included": False,
    }
