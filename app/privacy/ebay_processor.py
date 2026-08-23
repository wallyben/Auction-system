"""Persist and process verified eBay account-deletion notifications."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.orm import EbayDeletionDeadLetter, EbayDeletionNotification
from app.privacy.ebay_deletion import DeletionResult, EbayUserDeletionService
from app.privacy.identifiers import DeletionIdentities, identifier_hash, payload_sha256

logger = get_logger("arie.privacy.ebay_processor")

_TERMINAL = {"processed", "processed_unknown_user", "processed_duplicate"}
_ACCEPTED_TOPICS = {
    "MARKETPLACE_ACCOUNT_DELETION",
    "MARKETPLACE_ACCOUNT_DELETION".replace("PLACE", "PLACE"),
}


def process_verified_notification(
    session: Session,
    *,
    identities: DeletionIdentities,
    body: bytes,
    signature_kid: str | None,
) -> DeletionResult:
    """Idempotently apply a signature-verified deletion notice.

    http_status 204 means eBay should stop retrying.
    http_status 500 means a temporary failure — eBay should retry.
    """
    notification_id = identities.notification_id or payload_sha256(body)
    existing = session.scalar(
        select(EbayDeletionNotification).where(
            EbayDeletionNotification.notification_id == notification_id
        )
    )
    if existing and existing.status in _TERMINAL:
        logger.info("ebay_deletion_duplicate", notification_id=notification_id, status=existing.status)
        return DeletionResult(
            status="processed_duplicate",
            http_status=204,
            notification_id=notification_id,
            records_deleted=dict(existing.records_deleted or {}),
            records_anonymised=dict(existing.records_anonymised or {}),
            accountant_or_legal_review_required=bool(existing.accountant_or_legal_review_required),
            duplicate=True,
            unknown_user=existing.status == "processed_unknown_user",
        )

    row = existing or EbayDeletionNotification(
        notification_id=notification_id,
        topic=identities.topic or "MARKETPLACE_ACCOUNT_DELETION",
        received_at=datetime.now(timezone.utc),
        status="received",
        attempts=0,
        username_hash=identifier_hash(identities.username),
        user_id_hash=identifier_hash(identities.user_id),
        eias_hash=identifier_hash(identities.eias_token),
        payload_sha256=payload_sha256(body),
        signature_kid=signature_kid,
        schema_version=identities.schema_version,
    )
    if existing is None:
        session.add(row)
        session.flush()
    row.attempts = int(row.attempts or 0) + 1
    row.status = "processing"
    try:
        with session.begin_nested():
            result = EbayUserDeletionService().process(session, identities)
        row.status = result.status
        row.processed_at = datetime.now(timezone.utc)
        row.records_deleted = result.records_deleted
        row.records_anonymised = result.records_anonymised
        row.accountant_or_legal_review_required = result.accountant_or_legal_review_required
        row.last_error_class = None
        result.notification_id = notification_id
        return result
    except Exception as exc:  # noqa: BLE001 — record failure class, not PII
        logger.exception("ebay_deletion_processing_failed", notification_id=notification_id)
        row.status = "failed"
        row.last_error_class = type(exc).__name__
        _upsert_dead_letter(session, notification_id, type(exc).__name__, payload_sha256(body))
        return DeletionResult(
            status="failed",
            http_status=500,
            notification_id=notification_id,
            error=type(exc).__name__,
        )


def record_unparseable_notice(
    session: Session,
    *,
    body: bytes,
    signature_kid: str | None,
    reason: str,
) -> DeletionResult:
    """Signature was valid but the body could not be interpreted as a deletion notice.

    Acknowledge with 204 so eBay does not disable the endpoint, without claiming
    that user data was deleted. No plaintext PII is stored.
    """
    notification_id = f"unparseable:{payload_sha256(body)}"
    existing = session.scalar(
        select(EbayDeletionNotification).where(
            EbayDeletionNotification.notification_id == notification_id
        )
    )
    if existing:
        existing.attempts = int(existing.attempts or 0) + 1
        return DeletionResult(
            status="received_unparseable",
            http_status=204,
            notification_id=notification_id,
            duplicate=True,
        )
    session.add(
        EbayDeletionNotification(
            notification_id=notification_id,
            topic="UNPARSEABLE",
            received_at=datetime.now(timezone.utc),
            processed_at=datetime.now(timezone.utc),
            status="received_unparseable",
            attempts=1,
            payload_sha256=payload_sha256(body),
            signature_kid=signature_kid,
            last_error_class=reason,
        )
    )
    _upsert_dead_letter(session, notification_id, reason, payload_sha256(body))
    logger.warning("ebay_deletion_unparseable_signed_payload", reason=reason)
    return DeletionResult(
        status="received_unparseable",
        http_status=204,
        notification_id=notification_id,
        error=reason,
    )


def retry_failed_deletions(session: Session, *, limit: int = 20) -> int:
    """Mark stale processing rows failed. Full replay requires eBay HTTP retry."""
    stuck = list(
        session.scalars(
            select(EbayDeletionNotification)
            .where(EbayDeletionNotification.status == "processing")
            .limit(limit)
        ).all()
    )
    for row in stuck:
        row.status = "failed"
        row.last_error_class = row.last_error_class or "StuckProcessing"
        _upsert_dead_letter(session, row.notification_id, "StuckProcessing", row.payload_sha256)
    return len(stuck)


def _upsert_dead_letter(session: Session, notification_id: str, error_class: str, payload_hash: str | None) -> None:
    existing = session.scalar(
        select(EbayDeletionDeadLetter).where(
            EbayDeletionDeadLetter.notification_id == notification_id,
            EbayDeletionDeadLetter.resolved.is_(False),
        )
    )
    if existing:
        existing.attempts = int(existing.attempts or 0) + 1
        existing.last_error_class = error_class
        existing.payload_sha256 = payload_hash
        return
    session.add(
        EbayDeletionDeadLetter(
            notification_id=notification_id,
            attempts=1,
            last_error_class=error_class,
            payload_sha256=payload_hash,
            resolved=False,
        )
    )


process_verified_notification = process_verified_notification
record_unparseable_notice = record_unparseable_notice
retry_failed_deletions = retry_failed_deletions
