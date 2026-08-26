"""eBay endpoint challenge response — first-party Event Notification SDK algorithm.

Official algorithm (eBay event-notification Node/Java/Go SDKs, Apache-2.0):
SHA-256(challengeCode + verificationToken + endpoint) as lowercase hex.

Docs:
https://developer.ebay.com/marketplace-account-deletion
https://github.com/eBay/event-notification-nodejs-sdk
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from pathlib import Path

from app.privacy.identifiers import token_is_valid

_TOKEN_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"


def generate_verification_token(length: int = 48) -> str:
    """Generate a token that satisfies eBay's 32-80 charset constraint."""
    if length < 32 or length > 80:
        raise ValueError("verification token length must be 32-80")
    return "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(length))


def challenge_response(challenge_code: str, verification_token: str, endpoint: str) -> str:
    """Return the hex SHA-256 challengeResponse for a GET challenge_code."""
    digest = hashlib.sha256()
    digest.update(challenge_code.encode("utf-8"))
    digest.update(verification_token.encode("utf-8"))
    digest.update(endpoint.encode("utf-8"))
    return digest.hexdigest()


def write_token_to_env(env_path: Path | None = None) -> dict[str, object]:
    """Insert a verification token into .env without printing it.

    If a valid token already exists, it is left unchanged.
    """
    path = env_path or Path(".env")
    key = "EBAY_NOTIFICATION_VERIFICATION_TOKEN"
    existing = read_env_key(key, path) if path.exists() else None
    if existing and token_is_valid(existing):
        return {
            "action": "unchanged",
            "path": str(path),
            "token_configured": True,
            "token_length": len(existing),
            "token_valid": True,
        }
    token = generate_verification_token()
    upsert_env_key(key, token, path)
    return {
        "action": "written",
        "path": str(path),
        "token_configured": True,
        "token_length": len(token),
        "token_valid": True,
        "note": (
            "Token written to .env. Retrieve it with `make ebay-notification-show-token`. "
            "This command does not print the token."
        ),
    }


def write_endpoint_to_env(url: str, env_path: Path | None = None) -> dict[str, object]:
    """Persist EBAY_NOTIFICATION_ENDPOINT_URL without printing secrets.

    If the caller passes a host origin, the webhook path is appended. If they
    pass the full webhook URL, it is stored exactly (no trailing-slash rewrite).
    """
    path = env_path or Path(".env")
    raw = (url or "").strip()
    if not raw.startswith("https://"):
        return {
            "action": "rejected",
            "endpoint_https": False,
            "note": "Endpoint must be https:// with no secrets in the URL.",
        }
    if raw.rstrip("/").endswith("/webhooks/ebay/account-deletion"):
        endpoint = raw
    else:
        endpoint = raw.rstrip("/") + "/webhooks/ebay/account-deletion"
    upsert_env_key("EBAY_NOTIFICATION_ENDPOINT_URL", endpoint, path)
    return {
        "action": "written",
        "path": str(path),
        "endpoint_configured": True,
        "endpoint_https": endpoint.startswith("https://"),
        "endpoint_url": endpoint,
    }


def read_verification_token(env_path: Path | None = None) -> str:
    """Read the token from process env, then .env. Never log the value."""
    env_val = (os.environ.get("EBAY_NOTIFICATION_VERIFICATION_TOKEN") or "").strip()
    if env_val:
        return env_val
    return read_env_key("EBAY_NOTIFICATION_VERIFICATION_TOKEN", env_path) or ""


def read_endpoint_url(env_path: Path | None = None) -> str:
    env_val = (os.environ.get("EBAY_NOTIFICATION_ENDPOINT_URL") or "").strip()
    if env_val:
        return env_val
    return read_env_key("EBAY_NOTIFICATION_ENDPOINT_URL", env_path) or ""


def read_env_key(key: str, env_path: Path | None = None) -> str | None:
    path = env_path or Path(".env")
    if not path.exists():
        return None
    return _read_env_value(path.read_text(encoding="utf-8"), key)


def upsert_env_key(key: str, value: str, env_path: Path | None = None) -> Path:
    """Set KEY=value in .env, creating the file if needed. Does not print value."""
    path = env_path or Path(".env")
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    line = f"{key}={value}"
    if re.search(rf"^{re.escape(key)}=", text, flags=re.MULTILINE):
        text = re.sub(rf"^{re.escape(key)}=.*$", line, text, flags=re.MULTILINE)
        if not text.endswith("\n"):
            text += "\n"
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def _read_env_value(text: str, key: str) -> str | None:
    match = re.search(rf"^{re.escape(key)}=(.*)$", text, flags=re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip().strip('"').strip("'")


write_token_to_env = write_token_to_env
challenge_response = challenge_response
generate_verification_token = generate_verification_token
