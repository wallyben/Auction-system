"""FastAPI application entrypoint."""

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.core.config import settings


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.include_router(health_router)
    return app


app = create_app()
