"""Exclusive pipeline lease: scan/sold-refresh/revalue cannot overlap."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.jobs.lease import finish, release_memory, try_acquire


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
    release_memory()
    session = _session()
    first = try_acquire(session, "scan", "test")
    assert first is not None
    second = try_acquire(session, "revalue", "test")
    assert second is None
    finish(session, first, ok=True)
    third = try_acquire(session, "revalue", "test")
    assert third is not None
    finish(session, third, ok=True)
    session.close()
    release_memory()


def test_stale_lease_can_be_stolen() -> None:
    release_memory()
    session = _session()
    first = try_acquire(session, "scan", "test")
    assert first is not None
    first.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    session.flush()
    release_memory()
    stolen = try_acquire(session, "revalue", "test")
    assert stolen is not None
    assert first.status == "failed"
    assert first.error == "stale_lease"
    finish(session, stolen, ok=True)
    session.close()
    release_memory()
