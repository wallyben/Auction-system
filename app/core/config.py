"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings for the API service."""

    app_name: str = "ARIE API"
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str | None = os.getenv("DATABASE_URL")

    @property
    def database_url_required(self) -> str:
        """Return configured database URL or raise a descriptive error."""
        if not self.database_url:
            raise RuntimeError(
                "DATABASE_URL environment variable is required for database operations."
            )
        return self.database_url


settings = Settings()
