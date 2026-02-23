"""Database engine and session factory configuration."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Create and cache a SQLAlchemy engine."""
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url_required, pool_pre_ping=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Create and cache a SQLAlchemy session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )
    return _session_factory


def get_db_session() -> Generator[Session, None, None]:
    """Yield a database session and always close it."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
