"""Run Alembic upgrades at process start without printing credentials."""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.url import alembic_config_url, clean_database_url, describe_database_url

logger = get_logger("arie.db.migrate")


def alembic_ini_path() -> Path:
    return Path(__file__).resolve().parents[2] / "alembic.ini"


def run_startup_migrations() -> None:
    """Upgrade to head when DATABASE_URL is configured. Idempotent."""
    settings = get_settings()
    raw = clean_database_url(settings.database_url)
    diag = describe_database_url(raw)
    if not diag["configured"]:
        logger.info("startup_migrations_skipped", reason="database_url_not_configured")
        return
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(alembic_ini_path()))
    cfg.set_main_option("sqlalchemy.url", alembic_config_url(settings.database_url_required))
    logger.info(
        "startup_migrations_begin",
        scheme=diag["scheme"],
        sqlalchemy_scheme=diag["sqlalchemy_scheme"],
        host_present=diag["host_present"],
        database_present=diag["database_present"],
    )
    command.upgrade(cfg, "head")
    logger.info("startup_migrations_ok")
