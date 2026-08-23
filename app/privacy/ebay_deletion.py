"""Erase eBay user identity from ARIE after a verified deletion notice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.logging import get_logger
from app.models.orm import (
    Alert,
    AuditEvent,
    Comparable,
    InventoryItem,
    Listing,
    LossPostmortem,
    MetricEvent,
    Opportunity,
    Outcome,
    OwnerSale,
    PaperTrade,
    Purchase,
    RawListing,
    Sale,
    ScanJob,
    SoldEvidence,
    SourceHealth,
    Valuation,
    WatchlistItem,
)
from app.privacy.ebay_minimise import EBAY_SOURCE_ID, strip_seller_pii
from app.privacy.identifiers import DeletionIdentities

logger = get_logger("arie.privacy.ebay_deletion")

ACCOUNTANT_REQUIRED = "ACCOUNTANT_REQUIRED"
REDACTED = "[redacted]"


@dataclass
class DeletionResult:
    status: str
    http_status: int
    notification_id: str | None
    records_deleted: dict[str, int] = field(default_factory=dict)
    records_anonymised: dict[str, int] = field(default_factory=dict)
    accountant_or_legal_review_required: bool = False
    duplicate: bool = False
    unknown_user: bool = False
    error: str | None = None

    def bump(self, table: str, *, deleted: int = 0, anonymised: int = 0) -> None:
        if deleted:
            self.records_deleted[table] = self.records_deleted.get(table, 0) + deleted
        if anonymised:
            self.records_anonymised[table] = self.records_anonymised.get(table, 0) + anonymised


def _contains_identity(value: Any, needles: list[str], hashes: set[str]) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        for key, inner in value.items():
            if key in {"seller_username_hash", "seller_user_id_hash", "seller_eias_hash"} and inner in hashes:
                return True
            if _contains_identity(inner, needles, hashes):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_identity(item, needles, hashes) for item in value)
    text = str(value)
    lowered = text.lower()
    if any(needle.lower() == lowered or needle.lower() in lowered for needle in needles if needle):
        return True
    return text in hashes


def _redact_json(value: Any, needles: list[str], hashes: set[str]) -> tuple[Any, bool]:
    changed = False
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, inner in value.items():
            key_l = str(key).lower()
            if key in {"seller_username_hash", "seller_user_id_hash", "seller_eias_hash"}:
                out[key] = None
                changed = True
                continue
            if key_l in {"username", "userid", "user_id", "eiastoken", "eias_token", "seller"}:
                if isinstance(inner, str):
                    out[key] = None
                    changed = True
                    continue
            new_inner, inner_changed = _redact_json(inner, needles, hashes)
            changed = changed or inner_changed
            out[key] = new_inner
        return out, changed
    if isinstance(value, list):
        items = []
        for inner in value:
            new_inner, inner_changed = _redact_json(inner, needles, hashes)
            changed = changed or inner_changed
            items.append(new_inner)
        return items, changed
    if isinstance(value, str):
        lowered = value.lower()
        if any(needle.lower() == lowered or needle.lower() in lowered for needle in needles if needle):
            return REDACTED, True
    return value, False


def _redact_text(text: str | None, needles: list[str]) -> tuple[str | None, bool]:
    if not text:
        return text, False
    updated = text
    for needle in needles:
        if needle and needle in updated:
            updated = updated.replace(needle, REDACTED)
    return updated, updated != text


def listing_matches(listing: Listing, identities: DeletionIdentities) -> bool:
    if listing.source_id != EBAY_SOURCE_ID:
        return False
    hashes = identities.hashes()
    needles = identities.plaintext()
    if listing.seller and identities.username and listing.seller.lower() == identities.username.lower():
        return True
    extras = listing.extras or {}
    for key in ("seller_username_hash", "seller_user_id_hash", "seller_eias_hash"):
        if extras.get(key) in hashes:
            return True
    return _contains_identity(extras, needles, hashes) or _contains_identity(
        listing.description, needles, hashes
    )


def anonymise_listing(listing: Listing, identities: DeletionIdentities) -> bool:
    needles = identities.plaintext()
    hashes = identities.hashes()
    changed = False
    if listing.seller:
        listing.seller = None
        changed = True
    if listing.seller_location:
        listing.seller_location = None
        changed = True
    extras = dict(listing.extras or {})
    extras, extras_changed = _redact_json(extras, needles, hashes)
    extras["seller_present"] = False
    extras.pop("seller_feedback", None)
    extras.pop("seller_score", None)
    extras["ebay_account_deleted"] = True
    listing.extras = extras
    flag_modified(listing, "extras")
    desc, desc_changed = _redact_text(listing.description, needles)
    listing.description = desc or ""
    return changed or extras_changed or desc_changed


class EbayUserDeletionService:
    """Apply a verified MARKETPLACE_ACCOUNT_DELETION notice across ARIE tables."""

    def process(self, session: Session, identities: DeletionIdentities) -> DeletionResult:
        result = DeletionResult(
            status="processed",
            http_status=204,
            notification_id=identities.notification_id,
        )
        hashes = identities.hashes()
        needles = identities.plaintext()
        listings = list(session.scalars(select(Listing).where(Listing.source_id == EBAY_SOURCE_ID)).all())
        matched = [row for row in listings if listing_matches(row, identities)]
        listing_ids = {row.id for row in matched}
        matched_external = {row.external_id for row in matched}
        for listing in matched:
            if anonymise_listing(listing, identities):
                result.bump("listings", anonymised=1)

        for raw in session.scalars(select(RawListing).where(RawListing.source_id == EBAY_SOURCE_ID)).all():
            if not (
                _contains_identity(raw.payload, needles, hashes) or raw.external_id in matched_external
            ):
                continue
            raw.payload = strip_seller_pii(raw.payload or {})
            flag_modified(raw, "payload")
            result.bump("raw_listings", anonymised=1)

        for comp in session.scalars(select(Comparable)).all():
            if comp.source_id == EBAY_SOURCE_ID and (
                comp.subject_listing_id in listing_ids or _contains_identity(comp.extras, needles, hashes)
            ):
                comp.extras, changed = _redact_json(comp.extras or {}, needles, hashes)
                if changed:
                    flag_modified(comp, "extras")
                    result.bump("comparables", anonymised=1)

        for opp in session.scalars(select(Opportunity)).all():
            if opp.listing_id not in listing_ids and not _contains_identity(
                [opp.provenance_pack, opp.score_breakdown, opp.why], needles, hashes
            ):
                continue
            pack, c1 = _redact_json(opp.provenance_pack or {}, needles, hashes)
            breakdown, c2 = _redact_json(opp.score_breakdown or {}, needles, hashes)
            why, c3 = _redact_text(opp.why, needles)
            opp.provenance_pack = pack
            opp.score_breakdown = breakdown
            opp.why = why or opp.why
            if c1:
                flag_modified(opp, "provenance_pack")
            if c2:
                flag_modified(opp, "score_breakdown")
            if c1 or c2 or c3:
                result.bump("opportunities", anonymised=1)

        for val in session.scalars(select(Valuation)).all():
            if val.listing_id in listing_ids or _contains_identity(val.provenance, needles, hashes):
                val.provenance, changed = _redact_json(val.provenance or {}, needles, hashes)
                if changed:
                    flag_modified(val, "provenance")
                    result.bump("valuations", anonymised=1)

        for alert in session.scalars(select(Alert)).all():
            if not _contains_identity([alert.body, alert.payload, alert.title], needles, hashes):
                continue
            alert.body, _ = _redact_text(alert.body, needles)
            alert.title, _ = _redact_text(alert.title, needles)
            alert.payload, _ = _redact_json(alert.payload or {}, needles, hashes)
            flag_modified(alert, "payload")
            result.bump("alerts", anonymised=1)

        for event in session.scalars(select(AuditEvent)).all():
            if not _contains_identity(event.payload, needles, hashes):
                continue
            event.payload, _ = _redact_json(event.payload or {}, needles, hashes)
            flag_modified(event, "payload")
            result.bump("audit_events", anonymised=1)

        for watch in session.scalars(select(WatchlistItem)).all():
            if watch.kind.lower() in {"seller", "ebay_seller"} and watch.value:
                if identities.username and watch.value.lower() == identities.username.lower():
                    watch.value = REDACTED
                    watch.active = False
                    result.bump("watchlist_items", anonymised=1)
                    continue
            if watch.listing_id in listing_ids or _contains_identity(watch.value, needles, hashes):
                watch.value, changed = _redact_text(watch.value, needles)
                if changed:
                    result.bump("watchlist_items", anonymised=1)

        for sold in session.scalars(select(SoldEvidence)).all():
            if sold.source == EBAY_SOURCE_ID and _contains_identity(
                [sold.extras, sold.url_or_reference], needles, hashes
            ):
                sold.extras, _ = _redact_json(sold.extras or {}, needles, hashes)
                sold.url_or_reference, _ = _redact_text(sold.url_or_reference, needles)
                flag_modified(sold, "extras")
                result.bump("sold_evidence", anonymised=1)

        financial_touch = False
        for inv in session.scalars(select(InventoryItem)).all():
            if inv.listing_id in listing_ids or _contains_identity([inv.extras, inv.notes], needles, hashes):
                inv.extras, _ = _redact_json(inv.extras or {}, needles, hashes)
                inv.notes, _ = _redact_text(inv.notes, needles)
                flag_modified(inv, "extras")
                result.bump("inventory_items", anonymised=1)
                financial_touch = True

        for paper in session.scalars(select(PaperTrade)).all():
            if paper.listing_id in listing_ids or _contains_identity([paper.notes, paper.title], needles, hashes):
                paper.notes, _ = _redact_text(paper.notes, needles)
                paper.title, _ = _redact_text(paper.title, needles)
                result.bump("paper_trades", anonymised=1)

        for purchase in session.scalars(select(Purchase)).all():
            if purchase.listing_id in listing_ids or _contains_identity(purchase.notes, needles, hashes):
                note, _ = _redact_text(purchase.notes, needles)
                marker = f"{ACCOUNTANT_REQUIRED}: eBay seller identity removed; keep amounts/dates."
                purchase.notes = f"{note or ''}\n{marker}".strip()
                result.bump("purchases", anonymised=1)
                financial_touch = True

        for sale in session.scalars(select(Sale)).all():
            if _contains_identity(sale.notes, needles, hashes):
                sale.notes, _ = _redact_text(sale.notes, needles)
                result.bump("sales", anonymised=1)
                financial_touch = True

        for owner_sale in session.scalars(select(OwnerSale)).all():
            if _contains_identity([owner_sale.notes, getattr(owner_sale, "raw", None)], needles, hashes):
                owner_sale.notes, _ = _redact_text(owner_sale.notes, needles)
                if hasattr(owner_sale, "raw"):
                    owner_sale.raw, _ = _redact_json(owner_sale.raw or {}, needles, hashes)
                    flag_modified(owner_sale, "raw")
                result.bump("owner_sales", anonymised=1)
                financial_touch = True

        for outcome in session.scalars(select(Outcome)).all():
            if _contains_identity(outcome.extras, needles, hashes):
                outcome.extras, _ = _redact_json(outcome.extras or {}, needles, hashes)
                flag_modified(outcome, "extras")
                result.bump("outcomes", anonymised=1)
                financial_touch = True

        for postmortem in session.scalars(select(LossPostmortem)).all():
            if _contains_identity([postmortem.notes, postmortem.extras], needles, hashes):
                postmortem.notes, _ = _redact_text(postmortem.notes, needles)
                postmortem.extras, _ = _redact_json(postmortem.extras or {}, needles, hashes)
                flag_modified(postmortem, "extras")
                result.bump("loss_postmortems", anonymised=1)
                financial_touch = True

        for metric in session.scalars(select(MetricEvent)).all():
            if _contains_identity(metric.labels, needles, hashes):
                metric.labels, _ = _redact_json(metric.labels or {}, needles, hashes)
                flag_modified(metric, "labels")
                result.bump("metric_events", anonymised=1)

        for health in session.scalars(select(SourceHealth).where(SourceHealth.source_id == EBAY_SOURCE_ID)).all():
            if _contains_identity(health.proof, needles, hashes):
                health.proof, _ = _redact_json(health.proof or {}, needles, hashes)
                flag_modified(health, "proof")
                result.bump("source_health", anonymised=1)

        for job in session.scalars(select(ScanJob)).all():
            if _contains_identity(job.details, needles, hashes):
                job.details, _ = _redact_json(job.details or {}, needles, hashes)
                flag_modified(job, "details")
                result.bump("scan_jobs", anonymised=1)

        result.accountant_or_legal_review_required = financial_touch
        if not matched and not any(result.records_anonymised.values()):
            result.unknown_user = True
            result.status = "processed_unknown_user"
        logger.info(
            "ebay_user_deletion_applied",
            notification_id=identities.notification_id,
            listings=len(matched),
            unknown_user=result.unknown_user,
            accountant_or_legal_review_required=result.accountant_or_legal_review_required,
        )
        return result


EbayUserDeletionService = EbayUserDeletionService
DeletionResult = DeletionResult
listing_matches = listing_matches
anonymise_listing = anonymise_listing
