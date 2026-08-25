"""Identifier hashing and payload parsing for eBay deletion notices."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

PII_KEY_NAMES = {
    "username",
    "userid",
    "user_id",
    "eiastoken",
    "eias_token",
    "eiasToken",
    "seller",
    "sellerid",
    "seller_id",
    "sellerusername",
    "seller_username",
}

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,80}$")


def identifier_hash(value: str | None) -> str | None:
    """SHA-256 hex digest of a normalised identifier. None if empty."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return hashlib.sha256(text.lower().encode("utf-8")).hexdigest()


def token_is_valid(token: str) -> bool:
    """eBay verification tokens are 32-80 chars of A-Z a-z 0-9 _ -."""
    return bool(_TOKEN_RE.fullmatch(token or ""))


def payload_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


@dataclass(frozen=True, slots=True)
class DeletionIdentities:
    username: str | None
    user_id: str | None
    eias_token: str | None
    topic: str | None
    notification_id: str | None
    schema_version: str | None
    event_date: str | None
    publish_date: str | None
    publish_attempt_count: int | None

    def hashes(self) -> set[str]:
        out: set[str] = set()
        for value in (self.username, self.user_id, self.eias_token):
            digest = identifier_hash(value)
            if digest:
                out.add(digest)
        return out

    def plaintext(self) -> list[str]:
        return [value for value in (self.username, self.user_id, self.eias_token) if value]


def parse_deletion_payload(payload: dict[str, Any]) -> DeletionIdentities | None:
    """Extract identities from current eBay MARKETPLACE_ACCOUNT_DELETION JSON.

    Official Notification API shape (Commerce Notification):
    metadata.topic, notification.notificationId, notification.data.{username,userId,eiasToken}.
    """
    if not isinstance(payload, dict):
        return None
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    notification = payload.get("notification") if isinstance(payload.get("notification"), dict) else {}
    data = notification.get("data") if isinstance(notification.get("data"), dict) else {}
    if not data:
        # Older/sample docs sometimes nest data one level higher.
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    username = _first_str(data, "username", "userName", "user_name")
    user_id = _first_str(data, "userId", "userid", "user_id")
    eias = _first_str(data, "eiasToken", "eias_token", "eias")
    topic = _first_str(metadata, "topic") or _first_str(payload, "topic")
    notification_id = _first_str(notification, "notificationId", "notification_id") or _first_str(
        payload, "notificationId"
    )
    if not notification_id and not (username or user_id or eias):
        return None
    attempt = notification.get("publishAttemptCount")
    try:
        attempt_i = int(attempt) if attempt is not None else None
    except (TypeError, ValueError):
        attempt_i = None
    return DeletionIdentities(
        username=username,
        user_id=user_id,
        eias_token=eias,
        topic=topic,
        notification_id=notification_id,
        schema_version=_first_str(metadata, "schemaVersion", "schema_version"),
        event_date=_first_str(notification, "eventDate", "event_date"),
        publish_date=_first_str(notification, "publishDate", "publish_date"),
        publish_attempt_count=attempt_i,
    )


def _first_str(obj: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = obj.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


parse_deletion_payload = parse_deletion_payload
token_is_valid = token_is_valid
identifier_hash = identifier_hash
payload_sha256 = payload_sha256
