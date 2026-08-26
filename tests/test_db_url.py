"""Render DATABASE_URL normalization and secret-free diagnostics."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine.url import make_url

from app.core.config import get_settings
from app.db.session import get_db_session, get_engine, get_session_factory, probe_database, reset_engine
from app.db.url import classify_db_error, describe_database_url, normalize_database_url


RENDER_INTERNAL = "postgresql://arie:arie@dpg-example-a/arie"
RENDER_EXTERNAL = "postgresql://arie:arie@dpg-example-a.oregon-postgres.render.com/arie"
RENDER_POSTGRES_SCHEME = "postgres://arie:arie@dpg-example-a/arie"
LOCAL_RENDER_SHAPE = "postgresql://arie:arie@127.0.0.1:5432/arie"


def _reload() -> None:
    get_settings.cache_clear()
    reset_engine()


def test_render_postgresql_url_normalizes_to_psycopg() -> None:
    normalized = normalize_database_url(RENDER_INTERNAL)
    parsed = make_url(normalized)
    assert parsed.drivername == "postgresql+psycopg"
    assert parsed.host == "dpg-example-a"
    assert parsed.database == "arie"
    assert "sslmode" not in parsed.query
    assert "arie:arie" not in describe_database_url(RENDER_INTERNAL).values()


def test_render_postgres_scheme_normalizes_to_psycopg() -> None:
    parsed = make_url(normalize_database_url(RENDER_POSTGRES_SCHEME))
    assert parsed.drivername == "postgresql+psycopg"


def test_quoted_and_whitespace_database_url() -> None:
    raw = '  "postgresql://arie:s3cret@dpg-example-a/arie"  '
    parsed = make_url(normalize_database_url(raw))
    assert parsed.drivername == "postgresql+psycopg"
    assert parsed.host == "dpg-example-a"
    diag = describe_database_url(raw)
    assert diag["configured"] is True
    assert diag["scheme"] == "postgresql"
    assert diag["sqlalchemy_scheme"] == "postgresql+psycopg"
    assert diag["host_present"] is True
    assert diag["database_present"] is True
    assert "s3cret" not in str(diag)


def test_render_external_url_adds_sslmode_require() -> None:
    parsed = make_url(normalize_database_url(RENDER_EXTERNAL))
    assert parsed.drivername == "postgresql+psycopg"
    assert parsed.query.get("sslmode") == "require"


def test_existing_sslmode_is_preserved() -> None:
    raw = "postgresql://arie:arie@dpg-example-a.oregon-postgres.render.com/arie?sslmode=verify-full"
    parsed = make_url(normalize_database_url(raw))
    assert parsed.query.get("sslmode") == "verify-full"


def test_sqlite_url_is_not_rewritten() -> None:
    parsed = make_url(normalize_database_url("sqlite://"))
    assert parsed.drivername == "sqlite"


def test_psycopg_url_is_left_intact() -> None:
    raw = "postgresql+psycopg://arie:arie@localhost:5432/arie"
    parsed = make_url(normalize_database_url(raw))
    assert parsed.drivername == "postgresql+psycopg"
    assert parsed.host == "localhost"
    assert parsed.database == "arie"
    assert parsed.port == 5432


def test_describe_never_includes_password() -> None:
    diag = describe_database_url("postgresql://owner:super-secret-pass@dbhost/prod")
    dumped = str(diag)
    assert "super-secret-pass" not in dumped
    assert "owner" not in dumped


def test_unnormalized_postgresql_scheme_loads_psycopg2(monkeypatch: pytest.MonkeyPatch) -> None:
    """Document why Render's postgresql:// URL 500s without normalization.

    SQLAlchemy 2.x binds postgresql:// to psycopg2. This image ships psycopg v3.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises((ModuleNotFoundError, ImportError)):
        create_engine(RENDER_INTERNAL)


def test_missing_database_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _reload()
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        get_engine()


def test_failed_db_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://arie:arie@127.0.0.1:1/arie")
    _reload()
    result = probe_database()
    assert result["ok"] is False
    assert result["configured"] is True
    assert result["scheme"] == "postgresql"
    assert result["sqlalchemy_scheme"] == "postgresql+psycopg"
    assert result["host_present"] is True
    assert result["connection"] == "fail"
    assert result["reason"] in {"connect_failed", "error"}
    assert "arie:arie" not in str(result)


def _postgres_available() -> str | None:
    url = os.environ.get("TEST_DATABASE_URL", LOCAL_RENDER_SHAPE)
    try:
        engine = create_engine(
            normalize_database_url(url),
            connect_args={"connect_timeout": 2},
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return url
    except Exception:
        return None


@pytest.fixture()
def postgres_url(monkeypatch: pytest.MonkeyPatch) -> str:
    url = _postgres_available()
    if url is None:
        pytest.skip("PostgreSQL is not available")
    monkeypatch.setenv("DATABASE_URL", url)
    _reload()
    from app.db.migrate import run_startup_migrations

    run_startup_migrations()
    _reload()
    return url


def test_valid_db_connection_render_url_shape(postgres_url: str) -> None:
    engine = get_engine()
    assert engine.dialect.driver == "psycopg"
    factory = get_session_factory()
    session = factory()
    try:
        assert session.execute(text("SELECT 1")).scalar() == 1
        from app.models.orm import Source

        session.execute(select(Source).limit(1)).all()
    finally:
        session.close()
    gen = get_db_session()
    sess = next(gen)
    try:
        assert sess.execute(text("SELECT 1")).scalar() == 1
    finally:
        try:
            next(gen, None)
        except StopIteration:
            pass
    result = probe_database()
    assert result["ok"] is True
    assert result["connection"] == "ok"
    assert result["select_1"] == "ok"
    assert result["schema"] == "ok"
    assert result["scheme"] == "postgresql"
    assert result["sqlalchemy_scheme"] == "postgresql+psycopg"


def test_classify_driver_error() -> None:
    assert classify_db_error(ModuleNotFoundError("No module named 'psycopg2'")) == "driver_unavailable"
    assert classify_db_error(RuntimeError("DATABASE_URL environment variable is required for database operations.")) == (
        "not_configured"
    )
