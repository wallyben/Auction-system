"""FastAPI application entrypoint. HTTP only — no scheduler, no pipeline work."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.ebay_oauth import router as ebay_oauth_router
from app.api.routes.ebay_webhooks import router as ebay_webhook_router
from app.api.routes.ops import router as ops_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.process import is_web_process
from app.core.runtime import process_runtime_snapshot
from app.web.observability import RequestTelemetryMiddleware, start_observability, stop_observability


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    log = get_logger("arie.web")
    if "pytest" not in sys.modules and os.environ.get("ARIE_WEB_RUN_MIGRATIONS") == "1":
        from app.db.migrate import run_startup_migrations

        try:
            run_startup_migrations()
        except Exception:
            get_logger("arie.startup").exception("startup_migrations_failed")
    elif "pytest" not in sys.modules:
        log.info("web_startup_migrations_skipped", reason="scripts/start.sh_owns_alembic")
    runtime = process_runtime_snapshot()
    log.info("web_process_started", **runtime)
    if is_web_process():
        start_observability()
    try:
        yield
    finally:
        stop_observability()
        log.info("web_process_stopping", **process_runtime_snapshot())


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    application = FastAPI(
        title=settings.app_name,
        version="2.0.0",
        description="ARIE — Automated Reseller Intelligence Engine for Irish resale economics.",
        lifespan=lifespan,
    )
    application.add_middleware(RequestTelemetryMiddleware)
    static_dir = Path("app/web/static")
    static_dir.mkdir(parents=True, exist_ok=True)
    application.mount("/static", StaticFiles(directory=static_dir), name="static")
    application.include_router(ops_router)
    application.include_router(ebay_webhook_router)
    application.include_router(ebay_oauth_router)
    application.include_router(dashboard_router)
    return application


app = create_app()
