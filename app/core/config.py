"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for ARIE. Ordinary owner knobs live here, not in code."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "ARIE"
    app_env: str = "development"
    database_url: str | None = None

    home_country: str = "IE"
    base_currency: str = "EUR"

    min_profit_eur: str = "40"
    min_roi: str = "0.20"
    min_confidence: str = "0.55"
    max_capital_per_item_eur: str = "1500"
    max_days_to_sale: int = 45
    target_margin_percent: str = "0.15"
    risk_percent: str = "0.08"
    risk_tolerance: Literal["low", "medium", "high"] = "medium"

    enabled_sources: str = (
        "reverb,scryfall,csv_import,manual,rss_generic,ecb_fx,ebay_browse"
    )
    enabled_categories: str = (
        "consumer_electronics,computing,cameras,gaming,pro_av,music_dj,"
        "collectibles,trading_cards,tools,sporting_goods,hobby,small_business"
    )
    scan_queries: str = (
        "sol ring,lightning bolt,rhystic study,"
        "sony a7,canon rf,iphone 14,macbook air,nintendo switch,dewalt 18v"
    )
    scan_enabled: bool = True
    fast_marketplace_minutes: int = 15
    slow_source_minutes: int = 45
    auction_catalogue_minutes: int = 180
    valuation_refresh_hours: int = 12
    rss_urls: str = ""
    strategy_profile: str = "balanced"

    arie_dashboard_token: str = ""

    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_env: Literal["production", "sandbox"] = "production"
    ebay_marketplaces: str = "EBAY_IE,EBAY_GB,EBAY_DE,EBAY_FR,EBAY_IT,EBAY_ES,EBAY_NL"

    reverb_token: str = ""
    discogs_token: str = ""
    discord_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    alert_email_to: str = ""

    owner_vat_registered: bool = True
    owner_uses_margin_scheme: bool = True
    vat_rate: str = "0.23"

    ebay_ie_final_value_fee: str = "0.129"
    ebay_ie_fee_vat: str = "0.23"
    returns_allowance: str = "0.03"
    warranty_allowance: str = "0.01"
    fx_spread: str = "0.012"
    payment_fee_percent: str = "0.019"
    payment_fee_fixed_eur: str = "0.25"

    http_user_agent: str = "ARIE/2.0 (Irish reseller intelligence; local operator)"
    request_timeout_seconds: float = 20.0

    @property
    def database_url_required(self) -> str:
        """Return configured database URL or raise a descriptive error."""
        if not self.database_url:
            raise RuntimeError(
                "DATABASE_URL environment variable is required for database operations."
            )
        return self.database_url

    def source_ids(self) -> list[str]:
        return [part.strip() for part in self.enabled_sources.split(",") if part.strip()]

    def category_ids(self) -> list[str]:
        return [part.strip() for part in self.enabled_categories.split(",") if part.strip()]

    def query_list(self) -> list[str]:
        return [part.strip() for part in self.scan_queries.split(",") if part.strip()]

    def ebay_marketplace_list(self) -> list[str]:
        return [part.strip() for part in self.ebay_marketplaces.split(",") if part.strip()]

    def d(self, attr: str):
        from decimal import Decimal

        return Decimal(str(getattr(self, attr)))

    def rss_url_list(self) -> list[str]:
        return [part.strip() for part in self.rss_urls.split(",") if part.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()


settings = get_settings()
