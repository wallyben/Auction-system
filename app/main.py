"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.ops import router as ops_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.jobs.scheduler import start_scheduler


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    start_scheduler()
    yield


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    application = FastAPI(
        title=settings.app_name,
        version="2.0.0",
        description="ARIE — Automated Reseller Intelligence Engine for Irish resale economics.",
        lifespan=lifespan,
    )
    static_dir = Path("app/web/static")
    static_dir.mkdir(parents=True, exist_ok=True)
    application.mount("/static", StaticFiles(directory=static_dir), name="static")
    application.include_router(ops_router)
    application.include_router(dashboard_router)
    return application


app = create_app()
