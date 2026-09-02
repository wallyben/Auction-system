"""Query-driven eBay deletion: no full-table ORM scans, idempotent retries."""

from __future__ import annotations

import gc
import json
import re
import time
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func as sqlfunc, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.runtime import rss_mb
from app.db.base import Base
from app.models.orm import (
    Comparable,
    EbayDeletionNotification,
    Listing,
    Opportunity,
    SoldEvidence,
    Valuation,
    WatchlistItem,
)
from app.privacy.ebay_deletion import EbayUserDeletionService
from app.privacy.ebay_processor import process_verified_notification
from app.privacy.identifiers import identifier_hash
from sqlalchemy.orm.attributes import flag_modified
from tests.test_ebay_account_deletion import TOPIC, _identities, _seed_seller, _seed_source


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ARG001
    return "JSON"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):  # noqa: ARG001
    return "CHAR(36)"


@pytest.fixture()
def engine():
    import app.models.orm  # noqa: F401

    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as sess:
        yield sess


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _comparable(
    session: Session, listing: Listing | None, *, fingerprint: str, extras: dict | None = None
) -> Comparable:
    row = Comparable(
        subject_listing_id=listing.id if listing else None,
        source_id="ebay_browse",
        evidence_type="sold",
        title="comp",
        price=Decimal("10.00"),
        currency="GBP",
        observed_at=_now(),
        fingerprint=fingerprint,
        extras=extras or {},
    )
    session.add(row)
    session.flush()
    return row


def _opportunity(session: Session, listing: Listing, *, why: str = "test") -> Opportunity:
    row = Opportunity(
        listing_id=listing.id,
        decision="REVIEW",
        score=Decimal("0"),
        expected_profit_eur=Decimal("0"),
        expected_roi=Decimal("0"),
        margin_percent=Decimal("0"),
        downside_profit_eur=Decimal("0"),
        upside_profit_eur=Decimal("0"),
        capital_required_eur=Decimal("0"),
        max_buy_eur=Decimal("0"),
        all_in_acquisition_eur=Decimal("0"),
        expected_resale_eur=Decimal("0"),
        expected_net_resale_eur=Decimal("0"),
        identity_confidence=Decimal("0"),
        valuation_confidence=Decimal("0"),
        condition_confidence=Decimal("0"),
        why=why,
        score_breakdown={"seller_username_hash": identifier_hash("seller_alpha")},
        cost_breakdown={},
        last_evaluated_at=_now(),
        provenance_pack={"seller": "seller_alpha"},
    )
    session.add(row)
    session.flush()
    return row


def _valuation(session: Session, listing: Listing) -> Valuation:
    row = Valuation(
        listing_id=listing.id,
        method="test",
        expected_sale_eur=Decimal("1"),
        quick_sale_eur=Decimal("1"),
        high_eur=Decimal("1"),
        low_eur=Decimal("1"),
        confidence=Decimal("0.5"),
        provenance={"seller_username_hash": identifier_hash("seller_alpha")},
        valued_at=_now(),
    )
    session.add(row)
    session.flush()
    return row


def _count_loads(model):
    loaded: list[object] = []

    def _on_load(target, _context) -> None:  # noqa: ANN001
        loaded.append(target)

    event.listen(model, "load", _on_load)
    return loaded, lambda: event.remove(model, "load", _on_load)


def test_no_full_table_select_all_in_deletion_service() -> None:
    src = Path("app/privacy/ebay_deletion.py").read_text(encoding="utf-8")
    compact = re.sub(r"\s+", "", src)
    for model in (
        "Listing",
        "RawListing",
        "Comparable",
        "Opportunity",
        "Valuation",
        "Alert",
        "AuditEvent",
        "WatchlistItem",
        "SoldEvidence",
        "InventoryItem",
        "PaperTrade",
        "Purchase",
        "Sale",
        "OwnerSale",
        "Outcome",
        "LossPostmortem",
        "MetricEvent",
        "SourceHealth",
        "ScanJob",
    ):
        assert f"select({model})).all()" not in compact
        assert f"select({model}).all()" not in compact
    assert "select(MetricEvent)" not in src
    assert "select(ScanJob)" not in src
    assert "select(SourceHealth)" not in src
    timeout_src = Path("app/db/session.py").read_text(encoding="utf-8")
    assert "statement_timeout=20000" in timeout_src
    assert "statement_timeout" not in src


def test_unknown_user_does_not_orm_load_50k_comparables(session: Session) -> None:
    _seed_source(session)
    now = _now()
    batch: list[dict] = []
    for i in range(50_000):
        batch.append(
            {
                "id": uuid.uuid4(),
                "source_id": "ebay_browse",
                "evidence_type": "sold",
                "title": f"unrelated-{i}",
                "condition_grade": "used",
                "country": "GB",
                "currency": "GBP",
                "price": Decimal("10.00"),
                "observed_at": now,
                "product_match_score": Decimal("0"),
                "condition_match_score": Decimal("0"),
                "evidence_weight": Decimal("0"),
                "outlier": False,
                "adjustment_notes": "",
                "fingerprint": f"bulk-{i}",
                "extras": {},
                "created_at": now,
                "updated_at": now,
            }
        )
        if len(batch) >= 500:
            session.bulk_insert_mappings(Comparable, batch)
            batch.clear()
    if batch:
        session.bulk_insert_mappings(Comparable, batch)
    session.commit()
    session.expunge_all()
    gc.collect()
    assert session.scalar(select(sqlfunc.count()).select_from(Comparable)) == 50_000

    loaded, stop = _count_loads(Comparable)
    before = rss_mb()
    t0 = time.monotonic()
    result = EbayUserDeletionService().process(session, _identities("nobody-unknown", "nid-scale"))
    duration = time.monotonic() - t0
    after = rss_mb()
    stop()
    assert result.unknown_user is True
    assert result.http_status == 204
    assert loaded == []
    comps_in_map = [obj for obj in session.identity_map.values() if isinstance(obj, Comparable)]
    assert comps_in_map == []
    assert duration < 5.0
    if before is not None and after is not None:
        assert after - before < 40.0


def test_matching_listing_only_touches_related_rows(session: Session) -> None:
    matched = _seed_seller(session, username="seller_alpha", external_id="hit-1")
    other = _seed_seller(session, username="seller_other", external_id="miss-1")
    other.extras = {
        **(other.extras or {}),
        "seller_username_hash": identifier_hash("seller_other"),
        "seller_user_id_hash": identifier_hash("uid-other"),
        "seller_eias_hash": identifier_hash("eias-other"),
    }
    flag_modified(other, "extras")
    session.commit()
    hit_comp = _comparable(
        session,
        matched,
        fingerprint="c-hit",
        extras={"seller_username_hash": identifier_hash("seller_alpha")},
    )
    miss_comp = _comparable(
        session,
        other,
        fingerprint="c-miss",
        extras={"seller_username_hash": identifier_hash("seller_other"), "keep": True},
    )
    hit_opp = _opportunity(session, matched, why="buy from seller_alpha")
    miss_opp = _opportunity(session, other, why="unrelated")
    miss_opp.provenance_pack = {"seller": "seller_other"}
    miss_opp.score_breakdown = {"seller_username_hash": identifier_hash("seller_other")}
    hit_val = _valuation(session, matched)
    miss_val = _valuation(session, other)
    miss_val.provenance = {"seller_username_hash": identifier_hash("seller_other")}
    session.add(WatchlistItem(kind="seller", value="seller_alpha", listing_id=None, active=True))
    session.add(WatchlistItem(kind="seller", value="seller_other", listing_id=None, active=True))
    session.add(
        SoldEvidence(
            canonical_product_id="cam",
            condition="used",
            channel="ebay",
            sold_price=Decimal("10"),
            sold_date=_now(),
            source="compsniper",
            fingerprint="sold-hit",
            extras={"seller": "seller_alpha"},
        )
    )
    session.add(
        SoldEvidence(
            canonical_product_id="cam",
            condition="used",
            channel="ebay",
            sold_price=Decimal("11"),
            sold_date=_now(),
            source="compsniper",
            fingerprint="sold-miss",
            extras={"seller": "seller_other"},
        )
    )
    session.commit()
    hit_comp_id = hit_comp.id
    miss_comp_id = miss_comp.id
    matched_id = matched.id
    other_id = other.id
    hit_opp_id = hit_opp.id
    miss_opp_id = miss_opp.id
    hit_val_id = hit_val.id
    miss_val_id = miss_val.id
    session.expunge_all()

    loaded, stop = _count_loads(Comparable)
    result = EbayUserDeletionService().process(session, _identities("seller_alpha", "nid-related"))
    stop()
    session.flush()
    assert result.unknown_user is False
    assert result.records_anonymised.get("listings") == 1
    assert result.records_anonymised.get("comparables") == 1
    assert result.records_anonymised.get("opportunities") == 1
    assert result.records_anonymised.get("valuations") == 1
    assert {row.id for row in loaded} == {hit_comp_id}

    matched = session.get(Listing, matched_id)
    other = session.get(Listing, other_id)
    hit_comp = session.get(Comparable, hit_comp_id)
    miss_comp = session.get(Comparable, miss_comp_id)
    hit_opp = session.get(Opportunity, hit_opp_id)
    miss_opp = session.get(Opportunity, miss_opp_id)
    hit_val = session.get(Valuation, hit_val_id)
    miss_val = session.get(Valuation, miss_val_id)
    assert matched is not None and other is not None
    assert hit_comp is not None and miss_comp is not None
    assert hit_opp is not None and miss_opp is not None
    assert hit_val is not None and miss_val is not None
    assert not (matched.extras or {}).get("seller_username_hash")
    assert (other.extras or {}).get("seller_username_hash") == identifier_hash("seller_other")
    assert not (hit_comp.extras or {}).get("seller_username_hash")
    assert (miss_comp.extras or {}).get("seller_username_hash") == identifier_hash("seller_other")
    assert "seller_alpha" not in (hit_opp.why or "")
    assert miss_opp.why == "unrelated"
    assert not (hit_val.provenance or {}).get("seller_username_hash")
    assert (miss_val.provenance or {}).get("seller_username_hash") == identifier_hash("seller_other")
    watches = {row.value: row.active for row in session.scalars(select(WatchlistItem)).all()}
    assert watches["[redacted]"] is False
    assert watches["seller_other"] is True
    sold = {
        row.fingerprint: (row.extras or {}).get("seller") for row in session.scalars(select(SoldEvidence)).all()
    }
    assert sold["sold-hit"] in {None, "[redacted]"}
    assert sold["sold-miss"] == "seller_other"


def test_duplicate_notification_skips_work(session: Session) -> None:
    _seed_seller(session)
    body = json.dumps({"notification": {"notificationId": "nid-dup"}}, separators=(",", ":")).encode()
    first = process_verified_notification(
        session, identities=_identities("seller_alpha", "nid-dup"), body=body, signature_kid="k"
    )
    session.commit()
    assert first.http_status == 204
    assert first.duplicate is False
    second = process_verified_notification(
        session, identities=_identities("seller_alpha", "nid-dup"), body=body, signature_kid="k"
    )
    assert second.http_status == 204
    assert second.duplicate is True
    rows = list(session.scalars(select(EbayDeletionNotification)))
    assert len(rows) == 1


def test_retry_after_failure(session: Session) -> None:
    listing = _seed_seller(session)
    session.add(
        EbayDeletionNotification(
            notification_id="nid-retry",
            topic=TOPIC,
            status="failed",
            attempts=2,
            last_error_class="QueryCanceled",
        )
    )
    session.commit()
    result = process_verified_notification(
        session, identities=_identities("seller_alpha", "nid-retry"), body=b"{}", signature_kid="k"
    )
    session.commit()
    assert result.http_status == 204
    assert result.duplicate is False
    session.refresh(listing)
    assert not (listing.extras or {}).get("seller_username_hash")
    row = session.scalars(select(EbayDeletionNotification)).first()
    assert row is not None
    assert row.status == "processed"
    assert row.attempts >= 3


def test_in_flight_processing_returns_500(session: Session) -> None:
    session.add(
        EbayDeletionNotification(
            notification_id="nid-inflight",
            topic=TOPIC,
            status="processing",
            attempts=1,
        )
    )
    session.commit()
    result = process_verified_notification(
        session,
        identities=_identities("seller_alpha", "nid-inflight"),
        body=b"{}",
        signature_kid="k",
    )
    assert result.http_status == 500
    assert result.error == "AlreadyProcessing"
    row = session.scalars(select(EbayDeletionNotification)).first()
    assert row is not None
    assert row.status == "processing"


def test_listing_match_sql_is_filtered() -> None:
    src = Path("app/privacy/ebay_deletion.py").read_text(encoding="utf-8")
    assert "Listing.source_id == EBAY_SOURCE_ID" in src
    assert "subject_listing_id" in src
    assert "Opportunity.listing_id" in src
    assert "Valuation.listing_id" in src
