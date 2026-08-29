"""Exclusive pipeline lease: scan/sold-refresh/revalue cannot overlap."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.jobs.queue import claim_next, enqueue, finish, recover_stale


@compiles(JSONB, "sqlite")
def _jsonb(type_, compiler, **kw):  # noqa: ARG001
    return "JSON"


@compiles(UUID, "sqlite")
def _uuid(type_, compiler, **kw):  # noqa: ARG001
    return "CHAR(36)"


def _session():
    import app.models.orm  # noqa: F401

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    factory = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    return factory()


def test_second_job_is_rejected_while_lease_held() -> None:
    session = _session()
    first, first_result = enqueue(session, "scan", "test")
    assert first is not None
    assert first_result["ok"] is True
    claimed = claim_next(session, "w1")
    assert claimed is not None
    second, second_result = enqueue(session, "revalue", "test")
    assert second is None
    assert second_result["reason"] == "busy"
    finish(session, claimed, ok=True)
    third, third_result = enqueue(session, "revalue", "test")
    assert third is not None
    assert third_result["ok"] is True
    session.close()


def test_stale_lease_can_be_stolen() -> None:
    session = _session()
    first, _ = enqueue(session, "scan", "test")
    assert first is not None
    claimed = claim_next(session, "w1")
    assert claimed is not None
    claimed.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    session.flush()
    recovered = recover_stale(session)
    assert str(claimed.id) in recovered
    stolen = claim_next(session, "w2")
    assert stolen is not None
    assert stolen.id == claimed.id
    assert stolen.claimed_by == "w2"
    finish(session, stolen, ok=True)
    session.close()
