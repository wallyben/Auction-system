"""Verify eBay X-EBAY-SIGNATURE using the official Event Notification algorithm.

Port of eBay's first-party SDKs (Apache-2.0):
- https://github.com/eBay/event-notification-nodejs-sdk
- https://github.com/eBay/event-notification-java-sdk
- https://github.com/eBay/event-notification-golang-sdk

There is no official Python Event Notification SDK. This module follows those
implementations: Base64-decode the signature header JSON, fetch the public key
by `kid` from the Notification API, ECDSA-SHA1 verify over the payload.

GET https://api.ebay.com/commerce/notification/v1/public_key/{public_key_id}
OAuth client-credentials. Cache keys for one hour (eBay guidance).
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.config import settings
from app.core.logging import get_logger
from app.sources.ebay import SCOPE, TOKEN_URL

logger = get_logger("arie.privacy.ebay_signature")

PUBLIC_KEY_URL = {
    "production": "https://api.ebay.com/commerce/notification/v1/public_key/",
    "sandbox": "https://api.sandbox.ebay.com/commerce/notification/v1/public_key/",
}

_KEY_START = "-----BEGIN PUBLIC KEY-----"
_KEY_END = "-----END PUBLIC KEY-----"
_CACHE_TTL_SECONDS = 3600.0
_cache: dict[str, tuple[float, "EbayPublicKey"]] = {}


@dataclass(frozen=True, slots=True)
class EbayPublicKey:
    kid: str
    pem: str
    algorithm: str
    digest: str


class SignatureError(Exception):
    """Raised when the signature header or key material cannot be used."""


def format_key(key: str) -> str:
    """Insert newlines around PEM banners, matching the official SDKs."""
    updated = key.replace(_KEY_START, f"{_KEY_START}\n")
    updated = updated.replace(_KEY_END, f"\n{_KEY_END}")
    return updated


def decode_signature_header(header: str) -> dict[str, Any]:
    try:
        raw = base64.b64decode(header)
        parsed = json.loads(raw.decode("ascii"))
    except Exception as exc:  # noqa: BLE001 — header is untrusted input
        raise SignatureError("malformed X-EBAY-SIGNATURE") from exc
    if not isinstance(parsed, dict) or "kid" not in parsed or "signature" not in parsed:
        raise SignatureError("signature header missing kid or signature")
    return parsed


def verify_payload(body: bytes, signature_header: str, public_key: EbayPublicKey) -> bool:
    """Return True if the ECDSA signature matches the body (or compact JSON)."""
    try:
        header = decode_signature_header(signature_header)
    except SignatureError:
        return False
    try:
        signature = base64.b64decode(header["signature"])
        pem = format_key(public_key.pem).encode("utf-8")
        key = serialization.load_pem_public_key(pem)
    except Exception:
        logger.warning("ebay_signature_key_parse_failed", kid=public_key.kid)
        return False
    candidates = [body]
    try:
        parsed = json.loads(body.decode("utf-8"))
        compact = json.dumps(parsed, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if compact != body:
            candidates.append(compact)
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    digest = hashes.SHA1() if (public_key.digest or "SHA1").upper() in {"SHA1", "SHA-1"} else hashes.SHA256()
    for message in candidates:
        try:
            key.verify(signature, message, ec.ECDSA(digest))  # type: ignore[union-attr]
            return True
        except (InvalidSignature, TypeError, ValueError):
            continue
    return False


async def fetch_public_key(kid: str, *, token: str | None = None) -> EbayPublicKey:
    """Fetch and cache eBay's notification public key for `kid`."""
    now = time.monotonic()
    cached = _cache.get(kid)
    if cached and cached[0] > now:
        return cached[1]
    access = token or await _app_token()
    env = settings.ebay_api_env
    url = PUBLIC_KEY_URL[env] + kid
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url, headers={"Authorization": f"Bearer {access}"})
    if response.status_code != 200:
        logger.warning(
            "ebay_public_key_fetch_failed",
            kid=kid,
            http_status=response.status_code,
        )
        raise SignatureError(f"public key fetch HTTP {response.status_code}")
    payload = response.json()
    pem = str(payload.get("key") or "")
    if not pem:
        raise SignatureError("public key response missing key")
    record = EbayPublicKey(
        kid=kid,
        pem=pem,
        algorithm=str(payload.get("algorithm") or "ECDSA"),
        digest=str(payload.get("digest") or "SHA1"),
    )
    _cache[kid] = (now + _CACHE_TTL_SECONDS, record)
    return record


def clear_public_key_cache() -> None:
    _cache.clear()


async def _app_token() -> str:
    if not settings.ebay_client_id or not settings.ebay_client_secret:
        raise SignatureError("eBay client credentials missing; cannot fetch notification public key")
    basic = base64.b64encode(
        f"{settings.ebay_client_id}:{settings.ebay_client_secret}".encode()
    ).decode()
    url = TOKEN_URL[settings.ebay_api_env]
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": SCOPE},
        )
    if response.status_code != 200:
        raise SignatureError(f"oauth for public key HTTP {response.status_code}")
    token = response.json().get("access_token")
    if not token:
        raise SignatureError("oauth response missing access_token")
    return str(token)


def signature_verifier_ready() -> bool:
    """True when the local verifier stack (cryptography) is importable."""
    try:
        serialization.load_pem_public_key  # noqa: B018
        return True
    except Exception:
        return False


signature_verifier_ready = signature_verifier_ready
decode_signature_header = decode_signature_header
fetch_public_key = fetch_public_key
verify_payload = verify_payload
