"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for ARIE. Ordinary owner knobs live here, not in code."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_ignore_empty=True,
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

    available_capital_eur: str = "5000"
    max_position_percent: str = "0.25"
    max_category_exposure: str = "0.40"
    max_purchase_eur: str = "1500"
    max_daily_capital_eur: str = "2000"
    max_weekly_capital_eur: str = "5000"
    max_single_item_loss_eur: str = "150"
    min_downside_margin: str = "0"
    buy_ready_min_identity: str = "0.90"
    buy_ready_min_condition: str = "0.75"
    buy_ready_min_valuation: str = "0.80"
    buy_ready_min_comps: int = 3
    buy_ready_require_realised: bool = True
    safe_start_mode: bool = True
    safe_start_max_purchase_eur: str = "250"
    safe_start_camera_max_purchase_eur: str = "1000"
    safe_start_camera_min_realised: int = 8
    safe_start_min_confidence: str = "0.85"
    owner_override_uncertified: bool = False
    certified_categories: str = ""
    certified_exits: str = "ebay_ie,local_ie"
    alert_on: str = "BUY_READY"
    labour_eur_per_hour: str = "25"

    enabled_sources: str = (
        "reverb,scryfall,csv_import,manual,rss_generic,ecb_fx,ebay_browse"
    )
    enabled_categories: str = (
        "consumer_electronics,computing,cameras,gaming,pro_av,music_dj,"
        "collectibles,trading_cards,tools,sporting_goods,hobby,small_business"
    )
    scan_queries: str = (
        "Sony A7 IV,Sony A7 III,Sony A7R IV,Sony A7R III,"
        "Canon EOS R6,Canon EOS R6 II,Canon EOS R5,"
        "Nikon Z6 II,Nikon Z7 II,Fujifilm X-T4,Fujifilm X-T5,"
        "Sony FE 24-70mm GM II,Canon RF 24-70 f/2.8,"
        "MacBook Pro 14 M3,iPhone 15 Pro 256GB,PlayStation 5,"
        "RTX 4070,Pioneer DDJ-1000,Shure SM7B"
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
    ebay_notification_verification_token: str = ""
    ebay_notification_endpoint_url: str = ""
    ebay_ru_name: str = ""
    ebay_oauth_redirect_uri: str = ""
    ebay_refresh_token: str = ""

    compsniper_api_key: str = ""
    compsniper_enabled: bool = False
    compsniper_hot_ttl_hours: int = 18
    compsniper_slow_ttl_hours: int = 60
    compsniper_buy_ready_max_evidence_age_days: int = 21
    compsniper_primary_marketplaces: str = "GB,DE,FR"

    @property
    def ebay_api_env(self) -> Literal["production", "sandbox"]:
        """Host follows the keyset. Never send SBX keys to production or PRD keys to sandbox."""
        cid = (self.ebay_client_id or "").upper()
        secret = (self.ebay_client_secret or "").upper()
        if "SBX" in cid or secret.startswith("SBX-"):
            return "sandbox"
        if "PRD" in cid or secret.startswith("PRD-"):
            return "production"
        return self.ebay_env

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

    @field_validator("database_url", mode="before")
    @classmethod
    def _strip_database_url(cls, value: object) -> str | None:
        from app.db.url import clean_database_url

        if value is None:
            return None
        return clean_database_url(str(value))

    @property
    def database_url_required(self) -> str:
        """Return a driver-correct SQLAlchemy URL or raise a descriptive error."""
        from app.db.url import clean_database_url, normalize_database_url

        raw = clean_database_url(self.database_url)
        if not raw:
            raise RuntimeError(
                "DATABASE_URL environment variable is required for database operations."
            )
        return normalize_database_url(raw)

    def source_ids(self) -> list[str]:
        return [part.strip() for part in self.enabled_sources.split(",") if part.strip()]

    def category_ids(self) -> list[str]:
        return [part.strip() for part in self.enabled_categories.split(",") if part.strip()]

    def query_list(self) -> list[str]:
        return [part.strip() for part in self.scan_queries.split(",") if part.strip()]

    def ebay_marketplace_list(self) -> list[str]:
        return [part.strip() for part in self.ebay_marketplaces.split(",") if part.strip()]

    def certified_category_list(self) -> list[str]:
        return [part.strip() for part in self.certified_categories.split(",") if part.strip()]

    def certified_exit_list(self) -> list[str]:
        return [part.strip() for part in self.certified_exits.split(",") if part.strip()]

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
