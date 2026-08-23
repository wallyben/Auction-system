"""eBay endpoint challenge response — first-party Event Notification SDK algorithm.

Official algorithm (eBay event-notification Node/Java/Go SDKs, Apache-2.0):
SHA-256(challengeCode + verificationToken + endpoint) as lowercase hex.

Docs:
https://developer.ebay.com/marketplace-account-deletion
https://github.com/eBay/event-notification-nodejs-sdk
"""

from __future__ import annotations

import hashlib
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
    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        example = Path(".env.example")
        text = example.read_text(encoding="utf-8") if example.exists() else ""
    existing = _read_env_value(text, key)
    if existing and token_is_valid(existing):
        return {
            "action": "unchanged",
            "path": str(path),
            "token_configured": True,
            "token_length": len(existing),
            "token_valid": True,
        }
    token = generate_verification_token()
    line = f"{key}={token}\n"
    if re.search(rf"^{key}=", text, flags=re.MULTILINE):
        text = re.sub(rf"^{key}=.*$", line.rstrip(), text, flags=re.MULTILINE)
        if not text.endswith("\n"):
            text += "\n"
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line
    path.write_text(text, encoding="utf-8")
    return {
        "action": "written",
        "path": str(path),
        "token_configured": True,
        "token_length": len(token),
        "token_valid": True,
        "note": "Token written to .env. Copy it from .env into the eBay Developer portal. This command does not print the token.",
    }


def _read_env_value(text: str, key: str) -> str | None:
    match = re.search(rf"^{key}=(.*)$", text, flags=re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip().strip('"').strip("'")


write_token_to_env = write_token_to_env
challenge_response = challenge_response
generate_verification_token = generate_verification_token
