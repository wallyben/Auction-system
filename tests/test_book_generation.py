"""Current valuation book: stale/partial algorithms never rank as current."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.orm import Listing, Opportunity, Source
from app.opportunity.book import (
    current_generation,
    current_opportunities,
    is_current_opportunity,
    promote_generation,
    start_generation,
)
from app.valuation.version import VALUATION_ALGORITHM_VERSION


@compiles(JSONB, "sqlite")
def _jsonb(type_, compiler, **kw):  # noqa: ARG001
    return "JSON"


@compiles(UUID, "sqlite")
def _uuid(type_, compiler, **kw):  # noqa: ARG001
    return "CHAR(36)"


def _session() -> Session:
    import app.models.orm  # noqa: F401

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    factory = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    session = factory()
    session.add(
        Source(
            id="manual",
            display_name="Manual",
            country="IE",
            kind="manual",
            official_api=False,
            access_method="csv",
            credentials_required=False,
            status="LIVE",
            status_reason="",
        )
    )
    session.flush()
    return session


def _listing(session: Session, index: int, title: str = "Sony A7 IV body only") -> Listing:
    now = datetime.now(timezone.utc)
    row = Listing(
        source_id="manual",
        external_id=f"ext-{index}",
        url=f"https://example.test/{index}",
        title=title,
        currency="EUR",
        asking_price=Decimal("900"),
        first_seen_at=now,
        last_seen_at=now,
        observed_at=now,
        fingerprint=f"fp-{index}",
        category="cameras",
        status="active",
    )
    session.add(row)
    session.flush()
    return row


def _opportunity(session: Session, listing: Listing, **overrides: object) -> Opportunity:
    now = datetime.now(timezone.utc)
    payload = dict(
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
        why="test",
        score_breakdown={},
        cost_breakdown={},
        last_evaluated_at=now,
        algorithm_version=VALUATION_ALGORITHM_VERSION,
        money_ready=False,
        money_ready_decision="REVIEW",
    )
    payload.update(overrides)
    row = Opportunity(**payload)
    session.add(row)
    session.flush()
    return row


def test_rankings_exclude_stale_algorithm_versions() -> None:
    session = _session()
    generation = start_generation(session, listings_total=2)
    promote_generation(session, generation)
    current_listing = _listing(session, 1)
    stale_listing = _listing(session, 2)
    current = _opportunity(session, current_listing, valuation_run_id=generation.id)
    stale = _opportunity(session, stale_listing, algorithm_version="2.1.1", valuation_run_id=generation.id)
    ranked = current_opportunities(session)
    ids = {row.id for row in ranked}
    assert current.id in ids
    assert stale.id not in ids
    assert is_current_opportunity(stale, generation) is False
    session.close()


@pytest.mark.asyncio
async def test_full_book_batching_processes_more_than_400(monkeypatch) -> None:
    session = _session()
    for index in range(450):
        _listing(session, index, title="Sony A7 IV body only")
    session.commit()
    seen: list[object] = []

    def stub_evaluate(sess, listing, comps, rates, live_cert=None, generation=None):
        seen.append(listing.id)
        return _opportunity(sess, listing, valuation_run_id=generation.id if generation else None)

    async def no_comps(*_args, **_kwargs):
        return []

    async def no_fx(_session):
        return {"EUR": Decimal("1")}

    monkeypatch.setattr("app.pipeline.service.evaluate_listing", stub_evaluate)
    monkeypatch.setattr("app.pipeline.service._comps_for", no_comps)
    monkeypatch.setattr("app.pipeline.service.refresh_fx", no_fx)
    monkeypatch.setattr("app.sold.certify.live_camera_body_certification", lambda *_a, **_k: {"certified": False})

    from app.pipeline.service import revalue_all_active

    result = await revalue_all_active(session, reason="test", batch_size=100)
    assert result["ok"] is True
    assert int(result["processed"]) == 450
    assert len(seen) == 450
    generation = current_generation(session)
    assert generation is not None
    assert generation.status == "current"
    assert str(generation.id) == result["generation"]
    session.close()


@pytest.mark.asyncio
async def test_partial_failed_revalue_does_not_become_current(monkeypatch) -> None:
    session = _session()
    for index in range(5):
        _listing(session, index)
    first = start_generation(session, listings_total=5)
    promote_generation(session, first)
    session.commit()

    def boom(*_args, **_kwargs):
        raise RuntimeError("injected revalue failure")

    async def no_comps(*_args, **_kwargs):
        return []

    async def no_fx(_session):
        return {"EUR": Decimal("1")}

    monkeypatch.setattr("app.pipeline.service.evaluate_listing", boom)
    monkeypatch.setattr("app.pipeline.service._comps_for", no_comps)
    monkeypatch.setattr("app.pipeline.service.refresh_fx", no_fx)
    monkeypatch.setattr("app.sold.certify.live_camera_body_certification", lambda *_a, **_k: {"certified": False})

    from app.pipeline.service import revalue_all_active

    with pytest.raises(RuntimeError, match="injected"):
        await revalue_all_active(session, reason="fail")
    session.expire_all()
    current = current_generation(session)
    assert current is not None
    assert current.id == first.id
    assert current.status == "current"
    from app.models.orm import BookGeneration

    failed = [
        row
        for row in session.scalars(select(BookGeneration)).all()
        if row.status == "failed"
    ]
    assert failed
    session.close()


@pytest.mark.asyncio
async def test_successful_revalue_promotes_new_generation(monkeypatch) -> None:
    session = _session()
    listing = _listing(session, 1)
    old = start_generation(session, listings_total=1)
    promote_generation(session, old)
    _opportunity(session, listing, valuation_run_id=old.id, algorithm_version="2.1.6")
    session.commit()

    def stub_evaluate(sess, listing_row, comps, rates, live_cert=None, generation=None):
        existing = sess.scalar(select(Opportunity).where(Opportunity.listing_id == listing_row.id))
        if existing is None:
            existing = _opportunity(sess, listing_row)
        existing.algorithm_version = VALUATION_ALGORITHM_VERSION
        existing.valuation_run_id = generation.id if generation else None
        return existing

    async def no_comps(*_args, **_kwargs):
        return []

    async def no_fx(_session):
        return {"EUR": Decimal("1")}

    monkeypatch.setattr("app.pipeline.service.evaluate_listing", stub_evaluate)
    monkeypatch.setattr("app.pipeline.service._comps_for", no_comps)
    monkeypatch.setattr("app.pipeline.service.refresh_fx", no_fx)
    monkeypatch.setattr("app.sold.certify.live_camera_body_certification", lambda *_a, **_k: {"certified": False})

    from app.pipeline.service import revalue_all_active

    result = await revalue_all_active(session, reason="promote")
    generation = current_generation(session)
    assert generation is not None
    assert generation.status == "current"
    assert generation.id != old.id
    assert str(generation.id) == result["generation"]
    opp = session.scalar(select(Opportunity).where(Opportunity.listing_id == listing.id))
    assert opp.valuation_run_id == generation.id
    assert is_current_opportunity(opp, generation) is True
    session.expire_all()
    old = session.get(type(generation), old.id)
    assert old.status == "superseded"
    session.close()


def test_blank_and_old_algorithm_rows_are_historical() -> None:
    session = _session()
    generation = start_generation(session, listings_total=1)
    promote_generation(session, generation)
    blank = _opportunity(session, _listing(session, 1), algorithm_version="", valuation_run_id=None)
    old = _opportunity(session, _listing(session, 2), algorithm_version="2.1.6", valuation_run_id=uuid4())
    assert is_current_opportunity(blank, generation) is False
    assert is_current_opportunity(old, generation) is False
    session.close()
