"""Database engine and session factory configuration."""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.url import (
    classify_db_error,
    clean_database_url,
    describe_database_url,
    normalize_database_url,
)

logger = get_logger("arie.db")

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def reset_engine() -> None:
    """Drop the cached engine. Used by tests when DATABASE_URL changes."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def _raw_database_url() -> str | None:
    return clean_database_url(os.environ.get("DATABASE_URL")) or clean_database_url(
        get_settings().database_url
    )


def engine_kwargs(url: str, process: str | None = None) -> dict[str, Any]:
    """Web SQL must fail closed. Worker jobs may run for minutes."""
    process = (process or os.environ.get("ARIE_PROCESS") or "web").strip().lower()
    kwargs: dict[str, Any] = {"pool_pre_ping": True, "pool_recycle": 280}
    if not url.startswith("postgresql"):
        return kwargs
    if process == "worker":
        kwargs["pool_size"] = 4
        kwargs["max_overflow"] = 2
        kwargs["connect_args"] = {"connect_timeout": 10}
        return kwargs
    kwargs["pool_size"] = 3
    kwargs["max_overflow"] = 2
    kwargs["connect_args"] = {
        "connect_timeout": 10,
        "options": "-c statement_timeout=20000",
    }
    return kwargs


def get_engine() -> Engine:
    """Create and cache a SQLAlchemy engine."""
    global _engine
    if _engine is None:
        raw = _raw_database_url()
        diag = describe_database_url(raw)
        logger.info(
            "database_engine_init",
            configured=diag["configured"],
            scheme=diag["scheme"],
            sqlalchemy_scheme=diag["sqlalchemy_scheme"],
            host_present=diag["host_present"],
            database_present=diag["database_present"],
        )
        if not raw:
            raise RuntimeError(
                "DATABASE_URL environment variable is required for database operations."
            )
        url = normalize_database_url(raw)
        kwargs = engine_kwargs(url)
        _engine = create_engine(url, **kwargs)
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
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def probe_database() -> dict[str, Any]:
    """Run a credential-free connectivity and schema check."""
    raw = _raw_database_url()
    diag = describe_database_url(raw)
    result: dict[str, Any] = {
        "ok": False,
        "reason": "not_configured",
        "configured": diag["configured"],
        "scheme": diag["scheme"],
        "sqlalchemy_scheme": diag["sqlalchemy_scheme"],
        "host_present": diag["host_present"],
        "database_present": diag["database_present"],
        "connection": "fail",
        "select_1": "fail",
        "schema": "fail",
        "migration_head": None,
    }
    if not diag["configured"]:
        return result
    try:
        normalize_database_url(raw or "")
        engine = get_engine()
        with engine.connect() as conn:
            result["connection"] = "ok"
            conn.execute(text("SELECT 1"))
            result["select_1"] = "ok"
            tables = set(inspect(conn).get_table_names())
            if "alembic_version" in tables:
                result["migration_head"] = conn.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
            if "sources" in tables:
                from app.models.orm import Source

                conn.execute(select(Source).limit(1))
                result["schema"] = "ok"
            else:
                result["reason"] = "schema_missing"
                return result
        result["ok"] = True
        result["reason"] = None
        return result
    except Exception as exc:  # noqa: BLE001 — must never leak the URL
        result["reason"] = classify_db_error(exc)
        logger.warning(
            "database_probe_failed",
            reason=result["reason"],
            error_class=type(exc).__name__,
            configured=diag["configured"],
            scheme=diag["scheme"],
            sqlalchemy_scheme=diag["sqlalchemy_scheme"],
            host_present=diag["host_present"],
            database_present=diag["database_present"],
        )
        return result
