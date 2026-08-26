"""Normalize and safely describe database URLs without exposing secrets.

Render's Internal/External Database URL uses ``postgresql://`` (sometimes
``postgres://``). SQLAlchemy treats unadorned ``postgresql://`` as the
psycopg2 dialect. This project ships ``psycopg`` v3 only, so the URL must
be rewritten to ``postgresql+psycopg://`` before ``create_engine``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine.url import make_url

# Unadorned schemes that SQLAlchemy would bind to a driver we do not ship.
_REWRITE_TO_PSYCOPG = frozenset({"postgres", "postgresql", "postgresql+psycopg2"})
_RENDER_EXTERNAL_SUFFIX = ".render.com"


def clean_database_url(raw: str | None) -> str | None:
    """Strip whitespace and a single layer of wrapping quotes. Empty → None."""
    if raw is None:
        return None
    text = str(raw).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    return text or None


def normalize_database_url(raw: str) -> str:
    """Return a SQLAlchemy URL that matches the installed psycopg v3 driver.

    Also adds ``sslmode=require`` for Render *external* hosts
    (``*.render.com``) when the URL does not already set sslmode. Internal
    Render hosts (no domain, e.g. ``dpg-xxxxx-a``) are left without SSL.
    """
    cleaned = clean_database_url(raw)
    if not cleaned:
        raise ValueError("database URL is empty")
    url = make_url(cleaned)
    driver = url.drivername
    if driver in _REWRITE_TO_PSYCOPG:
        url = url.set(drivername="postgresql+psycopg")
    host = (url.host or "").lower()
    query = {str(k).lower(): v for k, v in dict(url.query).items()}
    if host.endswith(_RENDER_EXTERNAL_SUFFIX) and "sslmode" not in query:
        url = url.update_query_dict({"sslmode": "require"})
    return url.render_as_string(hide_password=False)


def describe_database_url(raw: str | None) -> dict[str, Any]:
    """Secret-free description of a database URL. Never includes user/password."""
    cleaned = clean_database_url(raw)
    if not cleaned:
        return {
            "configured": False,
            "scheme": None,
            "sqlalchemy_scheme": None,
            "host_present": False,
            "database_present": False,
        }
    try:
        parsed = make_url(cleaned)
        normalized = make_url(normalize_database_url(cleaned))
    except Exception:  # noqa: BLE001 — untrusted env input
        return {
            "configured": True,
            "scheme": None,
            "sqlalchemy_scheme": None,
            "host_present": False,
            "database_present": False,
        }
    return {
        "configured": True,
        "scheme": parsed.drivername or None,
        "sqlalchemy_scheme": normalized.drivername or None,
        "host_present": bool(parsed.host),
        "database_present": bool(parsed.database),
    }


def classify_db_error(exc: BaseException) -> str:
    """Map an exception to a credential-free reason code."""
    name = type(exc).__name__
    message = str(exc)
    if name == "RuntimeError" and "DATABASE_URL" in message:
        return "not_configured"
    if name in {"ModuleNotFoundError", "NoSuchModuleError"}:
        return "driver_unavailable"
    if name in {"OperationalError", "InterfaceError", "TimeoutError"}:
        return "connect_failed"
    if name in {"ProgrammingError"}:
        return "schema_missing"
    return "error"


def alembic_config_url(url: str) -> str:
    """Escape ``%`` so ConfigParser interpolation does not corrupt passwords."""
    return url.replace("%", "%%")
