"""Erase eBay user identity from ARIE after a verified deletion notice.

Match graph (query-driven; never SELECT * FROM large tables):

    DeletionIdentities (username / userId / eIAS + hashes)
      → listings WHERE source_id='ebay_browse' AND (seller OR extras hash)
      → listing_ids / external_ids
      → raw_listings (source_id + external_id)
      → comparables (subject_listing_id)
      → opportunities / valuations (listing_id)
      → alerts (opportunity_id)
      → watchlist / inventory / paper_trades / purchases (listing_id)
      → sales / outcomes / loss_postmortems (purchase_id / inventory_id)
      → audit_events (entity_type=listing AND entity_id)

Residual (no listing FK, SQL predicates only, never .all()):
    watchlist_items WHERE kind in {seller, ebay_seller} AND lower(value)=username
    sold_evidence WHERE extras seller / hash equals identity
    owner_sales WHERE notes/raw identity (SQL), if plaintext present
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.sql import ColumnElement

from app.core.logging import get_logger
from app.models.orm import (
    Alert,
    AuditEvent,
    Comparable,
    InventoryItem,
    Listing,
    LossPostmortem,
    Opportunity,
    Outcome,
    OwnerSale,
    PaperTrade,
    Purchase,
    RawListing,
    Sale,
    SoldEvidence,
    Valuation,
    WatchlistItem,
)
from app.privacy.ebay_minimise import EBAY_SOURCE_ID, strip_seller_pii
from app.privacy.identifiers import DeletionIdentities

logger = get_logger("arie.privacy.ebay_deletion")

ACCOUNTANT_REQUIRED = "ACCOUNTANT_REQUIRED"
REDACTED = "[redacted]"
_HASH_KEYS = ("seller_username_hash", "seller_user_id_hash", "seller_eias_hash")
_SELLER_WATCH_KINDS = ("seller", "ebay_seller")


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
            if key in _HASH_KEYS and inner in hashes:
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
            if key in _HASH_KEYS:
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
    for key in _HASH_KEYS:
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


def _or(*clauses: ColumnElement[bool] | None) -> ColumnElement[bool] | None:
    present = [c for c in clauses if c is not None]
    if not present:
        return None
    if len(present) == 1:
        return present[0]
    return or_(*present)


def _in_values(column: Any, values: Iterable[Any]) -> ColumnElement[bool] | None:
    items = list(values)
    if not items:
        return None
    return column.in_(items)


def _json_hash_clause(column: Any, hashes: set[str]) -> ColumnElement[bool] | None:
    if not hashes:
        return None
    digest = list(hashes)
    return or_(*(column[key].as_string().in_(digest) for key in _HASH_KEYS))


def _json_seller_plaintext(column: Any, needles: list[str]) -> ColumnElement[bool] | None:
    if not needles:
        return None
    lowered = [n.lower() for n in needles]
    return or_(
        func.lower(column["seller"].as_string()).in_(lowered),
        func.lower(column["seller"]["username"].as_string()).in_(lowered),
        func.lower(column["username"].as_string()).in_(lowered),
    )


def _match_listings(session: Session, identities: DeletionIdentities) -> list[Listing]:
    hashes = identities.hashes()
    clauses: list[ColumnElement[bool]] = []
    if identities.username:
        clauses.append(func.lower(Listing.seller) == identities.username.lower())
    hash_clause = _json_hash_clause(Listing.extras, hashes)
    if hash_clause is not None:
        clauses.append(hash_clause)
    if not clauses:
        return []
    stmt = select(Listing).where(Listing.source_id == EBAY_SOURCE_ID, or_(*clauses))
    candidates = list(session.scalars(stmt).all())
    return [row for row in candidates if listing_matches(row, identities)]


def _load(session: Session, stmt: Any) -> list[Any]:
    return list(session.scalars(stmt).all())


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
        matched = _match_listings(session, identities)
        listing_ids = {row.id for row in matched}
        listing_id_strs = {str(row.id) for row in matched}
        matched_external = {row.external_id for row in matched}
        for listing in matched:
            if anonymise_listing(listing, identities):
                result.bump("listings", anonymised=1)

        self._raw_listings(session, result, matched_external)
        self._comparables(session, result, listing_ids, hashes, needles)
        opp_ids = self._opportunities(session, result, listing_ids, hashes, needles)
        self._valuations(session, result, listing_ids, hashes, needles)
        self._alerts(session, result, opp_ids, hashes, needles)
        self._audit_events(session, result, listing_id_strs, hashes, needles)
        self._watchlist(session, result, listing_ids, identities, hashes, needles)
        self._sold_evidence(session, result, hashes, needles)
        financial_touch = False
        inv_ids, inv_touched = self._inventory(session, result, listing_ids, hashes, needles)
        financial_touch = financial_touch or inv_touched
        self._paper_trades(session, result, listing_ids, hashes, needles)
        purchase_ids, touched = self._purchases(session, result, listing_ids, hashes, needles)
        financial_touch = financial_touch or touched
        financial_touch = self._sales(session, result, purchase_ids, hashes, needles) or financial_touch
        financial_touch = self._owner_sales(session, result, hashes, needles) or financial_touch
        financial_touch = self._outcomes(session, result, purchase_ids, hashes, needles) or financial_touch
        financial_touch = (
            self._loss_postmortems(session, result, inv_ids, purchase_ids, hashes, needles) or financial_touch
        )

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

    def _raw_listings(
        self, session: Session, result: DeletionResult, matched_external: set[str]
    ) -> None:
        clause = _in_values(RawListing.external_id, matched_external)
        if clause is None:
            return
        for raw in _load(
            session,
            select(RawListing).where(RawListing.source_id == EBAY_SOURCE_ID, clause),
        ):
            raw.payload = strip_seller_pii(raw.payload or {})
            flag_modified(raw, "payload")
            result.bump("raw_listings", anonymised=1)

    def _comparables(
        self,
        session: Session,
        result: DeletionResult,
        listing_ids: set[UUID],
        hashes: set[str],
        needles: list[str],
    ) -> None:
        clause = _in_values(Comparable.subject_listing_id, listing_ids)
        if clause is None:
            return
        for comp in _load(session, select(Comparable).where(clause)):
            comp.extras, changed = _redact_json(comp.extras or {}, needles, hashes)
            if changed:
                flag_modified(comp, "extras")
                result.bump("comparables", anonymised=1)

    def _opportunities(
        self,
        session: Session,
        result: DeletionResult,
        listing_ids: set[UUID],
        hashes: set[str],
        needles: list[str],
    ) -> set[UUID]:
        clause = _in_values(Opportunity.listing_id, listing_ids)
        if clause is None:
            return set()
        opp_ids: set[UUID] = set()
        for opp in _load(session, select(Opportunity).where(clause)):
            opp_ids.add(opp.id)
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
        return opp_ids

    def _valuations(
        self,
        session: Session,
        result: DeletionResult,
        listing_ids: set[UUID],
        hashes: set[str],
        needles: list[str],
    ) -> None:
        clause = _in_values(Valuation.listing_id, listing_ids)
        if clause is None:
            return
        for val in _load(session, select(Valuation).where(clause)):
            val.provenance, changed = _redact_json(val.provenance or {}, needles, hashes)
            if changed:
                flag_modified(val, "provenance")
                result.bump("valuations", anonymised=1)

    def _alerts(
        self,
        session: Session,
        result: DeletionResult,
        opp_ids: set[UUID],
        hashes: set[str],
        needles: list[str],
    ) -> None:
        clause = _in_values(Alert.opportunity_id, opp_ids)
        if clause is None:
            return
        for alert in _load(session, select(Alert).where(clause)):
            alert.body, _ = _redact_text(alert.body, needles)
            alert.title, _ = _redact_text(alert.title, needles)
            alert.payload, _ = _redact_json(alert.payload or {}, needles, hashes)
            flag_modified(alert, "payload")
            result.bump("alerts", anonymised=1)

    def _audit_events(
        self,
        session: Session,
        result: DeletionResult,
        listing_id_strs: set[str],
        hashes: set[str],
        needles: list[str],
    ) -> None:
        clause = _in_values(AuditEvent.entity_id, listing_id_strs)
        if clause is None:
            return
        for event in _load(
            session,
            select(AuditEvent).where(AuditEvent.entity_type == "listing", clause),
        ):
            event.payload, _ = _redact_json(event.payload or {}, needles, hashes)
            flag_modified(event, "payload")
            result.bump("audit_events", anonymised=1)

    def _watchlist(
        self,
        session: Session,
        result: DeletionResult,
        listing_ids: set[UUID],
        identities: DeletionIdentities,
        hashes: set[str],
        needles: list[str],
    ) -> None:
        clauses: list[ColumnElement[bool]] = []
        listing_clause = _in_values(WatchlistItem.listing_id, listing_ids)
        if listing_clause is not None:
            clauses.append(listing_clause)
        if identities.username:
            clauses.append(
                and_(
                    func.lower(WatchlistItem.kind).in_(_SELLER_WATCH_KINDS),
                    func.lower(WatchlistItem.value) == identities.username.lower(),
                )
            )
        if not clauses:
            return
        for watch in _load(session, select(WatchlistItem).where(or_(*clauses))):
            if watch.kind.lower() in _SELLER_WATCH_KINDS and watch.value:
                if identities.username and watch.value.lower() == identities.username.lower():
                    watch.value = REDACTED
                    watch.active = False
                    result.bump("watchlist_items", anonymised=1)
                    continue
            if watch.listing_id in listing_ids or _contains_identity(watch.value, needles, hashes):
                watch.value, changed = _redact_text(watch.value, needles)
                if changed:
                    result.bump("watchlist_items", anonymised=1)

    def _sold_evidence(
        self,
        session: Session,
        result: DeletionResult,
        hashes: set[str],
        needles: list[str],
    ) -> None:
        where = _or(_json_hash_clause(SoldEvidence.extras, hashes), _json_seller_plaintext(SoldEvidence.extras, needles))
        if where is None:
            return
        for sold in _load(session, select(SoldEvidence).where(where)):
            if not _contains_identity([sold.extras, sold.url_or_reference], needles, hashes):
                continue
            sold.extras, _ = _redact_json(sold.extras or {}, needles, hashes)
            sold.url_or_reference, _ = _redact_text(sold.url_or_reference, needles)
            flag_modified(sold, "extras")
            result.bump("sold_evidence", anonymised=1)

    def _inventory(
        self,
        session: Session,
        result: DeletionResult,
        listing_ids: set[UUID],
        hashes: set[str],
        needles: list[str],
    ) -> tuple[set[UUID], bool]:
        clause = _in_values(InventoryItem.listing_id, listing_ids)
        if clause is None:
            return set(), False
        ids: set[UUID] = set()
        touched = False
        for inv in _load(session, select(InventoryItem).where(clause)):
            ids.add(inv.id)
            inv.extras, _ = _redact_json(inv.extras or {}, needles, hashes)
            inv.notes, _ = _redact_text(inv.notes, needles)
            flag_modified(inv, "extras")
            result.bump("inventory_items", anonymised=1)
            touched = True
        return ids, touched

    def _paper_trades(
        self,
        session: Session,
        result: DeletionResult,
        listing_ids: set[UUID],
        hashes: set[str],
        needles: list[str],
    ) -> None:
        clause = _in_values(PaperTrade.listing_id, listing_ids)
        if clause is None:
            return
        for paper in _load(session, select(PaperTrade).where(clause)):
            paper.notes, _ = _redact_text(paper.notes, needles)
            paper.title, _ = _redact_text(paper.title, needles)
            result.bump("paper_trades", anonymised=1)

    def _purchases(
        self,
        session: Session,
        result: DeletionResult,
        listing_ids: set[UUID],
        hashes: set[str],
        needles: list[str],
    ) -> tuple[set[UUID], bool]:
        clause = _in_values(Purchase.listing_id, listing_ids)
        if clause is None:
            return set(), False
        ids: set[UUID] = set()
        touched = False
        for purchase in _load(session, select(Purchase).where(clause)):
            ids.add(purchase.id)
            note, _ = _redact_text(purchase.notes, needles)
            marker = f"{ACCOUNTANT_REQUIRED}: eBay seller identity removed; keep amounts/dates."
            purchase.notes = f"{note or ''}\n{marker}".strip()
            result.bump("purchases", anonymised=1)
            touched = True
        return ids, touched

    def _sales(
        self,
        session: Session,
        result: DeletionResult,
        purchase_ids: set[UUID],
        hashes: set[str],
        needles: list[str],
    ) -> bool:
        clause = _in_values(Sale.purchase_id, purchase_ids)
        if clause is None:
            return False
        touched = False
        for sale in _load(session, select(Sale).where(clause)):
            sale.notes, changed = _redact_text(sale.notes, needles)
            if changed:
                result.bump("sales", anonymised=1)
            touched = True
        return touched

    def _owner_sales(
        self,
        session: Session,
        result: DeletionResult,
        hashes: set[str],
        needles: list[str],
    ) -> bool:
        clauses: list[ColumnElement[bool]] = []
        for needle in needles:
            clauses.append(OwnerSale.notes.contains(needle))
        hash_clause = _json_hash_clause(OwnerSale.raw, hashes)
        if hash_clause is not None:
            clauses.append(hash_clause)
        seller_clause = _json_seller_plaintext(OwnerSale.raw, needles)
        if seller_clause is not None:
            clauses.append(seller_clause)
        if not clauses:
            return False
        touched = False
        for owner_sale in _load(session, select(OwnerSale).where(or_(*clauses))):
            if not _contains_identity([owner_sale.notes, getattr(owner_sale, "raw", None)], needles, hashes):
                continue
            owner_sale.notes, _ = _redact_text(owner_sale.notes, needles)
            if hasattr(owner_sale, "raw"):
                owner_sale.raw, _ = _redact_json(owner_sale.raw or {}, needles, hashes)
                flag_modified(owner_sale, "raw")
            result.bump("owner_sales", anonymised=1)
            touched = True
        return touched

    def _outcomes(
        self,
        session: Session,
        result: DeletionResult,
        purchase_ids: set[UUID],
        hashes: set[str],
        needles: list[str],
    ) -> bool:
        clause = _in_values(Outcome.purchase_id, purchase_ids)
        if clause is None:
            return False
        touched = False
        for outcome in _load(session, select(Outcome).where(clause)):
            outcome.extras, _ = _redact_json(outcome.extras or {}, needles, hashes)
            flag_modified(outcome, "extras")
            result.bump("outcomes", anonymised=1)
            touched = True
        return touched

    def _loss_postmortems(
        self,
        session: Session,
        result: DeletionResult,
        inv_ids: set[UUID],
        purchase_ids: set[UUID],
        hashes: set[str],
        needles: list[str],
    ) -> bool:
        where = _or(
            _in_values(LossPostmortem.inventory_id, inv_ids),
            _in_values(LossPostmortem.purchase_id, purchase_ids),
        )
        if where is None:
            return False
        touched = False
        for postmortem in _load(session, select(LossPostmortem).where(where)):
            postmortem.notes, _ = _redact_text(postmortem.notes, needles)
            postmortem.extras, _ = _redact_json(postmortem.extras or {}, needles, hashes)
            flag_modified(postmortem, "extras")
            result.bump("loss_postmortems", anonymised=1)
            touched = True
        return touched


EbayUserDeletionService = EbayUserDeletionService
DeletionResult = DeletionResult
listing_matches = listing_matches
anonymise_listing = anonymise_listing
