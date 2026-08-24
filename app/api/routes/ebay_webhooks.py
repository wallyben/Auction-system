"""Public eBay Marketplace Account Deletion webhook.

No dashboard authentication. HTTPS is required in production (eBay rejects HTTP).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.privacy.ebay_challenge import challenge_response
from app.privacy.ebay_processor import process_verified_notification, record_unparseable_notice
from app.privacy.ebay_watch import record_watch_event
from app.privacy.ebay_signature import (
    SignatureError,
    decode_signature_header,
    fetch_public_key,
    verify_payload,
)
from app.privacy.identifiers import parse_deletion_payload, token_is_valid

logger = get_logger("arie.webhooks.ebay")

router = APIRouter(tags=["ebay-webhooks"])

_RATE_LIMIT = 180
_RATE_WINDOW = 60.0
_hits: dict[str, deque[float]] = defaultdict(deque)
_ACCEPTED_TOPICS = {"MARKETPLACE_ACCOUNT_DELETION"}


def get_db():
    yield from get_db_session()


def _rate_limit(key: str) -> bool:
    now = time.monotonic()
    bucket = _hits[key]
    while bucket and now - bucket[0] > _RATE_WINDOW:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT:
        return False
    bucket.append(now)
    return True


def reset_rate_limiter() -> None:
    _hits.clear()


def _endpoint_url() -> str:
    return (getattr(settings, "ebay_notification_endpoint_url", None) or "").strip()


def _token() -> str:
    return (getattr(settings, "ebay_notification_verification_token", None) or "").strip()


@router.get("/webhooks/ebay/account-deletion")
async def ebay_account_deletion_challenge(request: Request) -> JSONResponse:
    """eBay endpoint challenge (official SHA-256 algorithm).

    Official query parameter is `challenge_code`. `challengeCode` is accepted as an alias.
    Response body: {"challengeResponse": "<hex>"} with HTTP 200.
    Docs: https://developer.ebay.com/marketplace-account-deletion
    """
    client = request.client.host if request.client else "unknown"
    if not _rate_limit(f"get:{client}"):
        return JSONResponse({"error": "rate_limited"}, status_code=503)
    params = request.query_params
    challenge_code = params.get("challenge_code") or params.get("challengeCode")
    if not challenge_code:
        return JSONResponse({"error": "missing_challenge_code"}, status_code=400)
    record_watch_event("EBAY_CHALLENGE_RECEIVED", endpoint_host=_host(_endpoint_url()))
    token = _token()
    endpoint = _endpoint_url()
    if not token_is_valid(token) or not endpoint:
        logger.error("ebay_challenge_not_configured")
        return JSONResponse({"error": "endpoint_not_configured"}, status_code=500)
    response_hash = challenge_response(challenge_code, token, endpoint)
    logger.info("ebay_challenge_ok", endpoint_host=_host(endpoint))
    record_watch_event("EBAY_CHALLENGE_RESPONDED_200", endpoint_host=_host(endpoint))
    record_watch_event("EBAY_NOTIFICATION_ENDPOINT_VERIFIED", endpoint_host=_host(endpoint))
    return JSONResponse({"challengeResponse": response_hash}, status_code=200)


@router.post("/webhooks/ebay/account-deletion")
async def ebay_account_deletion_notice(
    request: Request,
    session: Session = Depends(get_db),
    x_ebay_signature: str | None = Header(default=None, alias="X-EBAY-SIGNATURE"),
) -> Response:
    """Verify signature then persist+process. 2xx only after durable processing.

    412 = invalid signature (do not delete).
    500 = temporary failure (eBay retries).
    204 = processed, duplicate, unknown user, or unparseable-after-valid-signature.
    """
    client = request.client.host if request.client else "unknown"
    if not _rate_limit(f"post:{client}"):
        return Response(status_code=503)
    body = await request.body()
    if not x_ebay_signature:
        logger.warning("ebay_deletion_missing_signature")
        record_watch_event("EBAY_POST_REJECTED_412", reason="missing_signature")
        return Response(status_code=412)
    try:
        header = decode_signature_header(x_ebay_signature)
        kid = str(header.get("kid") or "")
    except SignatureError:
        logger.warning("ebay_deletion_malformed_signature_header")
        return Response(status_code=412)
    try:
        public_key = await fetch_public_key(kid)
    except SignatureError:
        logger.warning("ebay_deletion_public_key_unavailable")
        return Response(status_code=500)
    if not verify_payload(body, x_ebay_signature, public_key):
        logger.warning("ebay_deletion_invalid_signature", kid=kid)
        return Response(status_code=412)
    try:
        try:
            payload = _parse_json(body)
        except ValueError:
            result = record_unparseable_notice(session, body=body, signature_kid=kid, reason="malformed_json")
            session.commit()
            return Response(status_code=result.http_status)
        identities = parse_deletion_payload(payload)
        if identities is None:
            result = record_unparseable_notice(
                session, body=body, signature_kid=kid, reason="unparseable_payload"
            )
            session.commit()
            return Response(status_code=result.http_status)
        topic = (identities.topic or "").upper()
        if topic and "ACCOUNT_DELETION" not in topic:
            logger.info("ebay_deletion_ignored_topic")
            session.commit()
            return Response(status_code=204)
        result = process_verified_notification(
            session,
            identities=identities,
            body=body,
            signature_kid=kid,
        )
        session.commit()
        return Response(status_code=result.http_status)
    except Exception:
        session.rollback()
        logger.exception("ebay_deletion_handler_failed")
        return Response(status_code=500)


def _parse_json(body: bytes) -> dict:
    import json

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid json") from exc
    if not isinstance(payload, dict):
        raise ValueError("json object required")
    return payload


def _host(url: str) -> str:
    try:
        from urllib.parse import urlparse

        return urlparse(url).netloc or "unset"
    except Exception:
        return "unset"
