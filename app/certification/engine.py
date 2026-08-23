"""Certification levels. Do not call LEVEL 5 without evidence."""

from __future__ import annotations

from app.core.config import settings
from app.models.enums import CategoryCert, CertificationLevel

CATEGORY_DEFAULTS = {
    "cameras": CategoryCert.NOT_CERTIFIED,
    "lenses": CategoryCert.NOT_CERTIFIED,
    "apple": CategoryCert.NOT_CERTIFIED,
    "computing": CategoryCert.NOT_CERTIFIED,
    "gaming": CategoryCert.NOT_CERTIFIED,
    "gpu": CategoryCert.NOT_CERTIFIED,
    "music_dj": CategoryCert.NOT_CERTIFIED,
    "pro_av": CategoryCert.NOT_CERTIFIED,
    "trading_cards": CategoryCert.NOT_CERTIFIED,
    "collectibles": CategoryCert.NOT_CERTIFIED,
    "tools": CategoryCert.NOT_CERTIFIED,
}

EXIT_DEFAULTS = {
    "ebay_ie": CategoryCert.NOT_CERTIFIED,
    "ebay_gb": CategoryCert.NOT_CERTIFIED,
    "local_ie": CategoryCert.NOT_CERTIFIED,
    "cardmarket": CategoryCert.NOT_CERTIFIED,
    "reverb": CategoryCert.NOT_CERTIFIED,
    "cex_trade_in": CategoryCert.NOT_CERTIFIED,
    "dealer": CategoryCert.NOT_CERTIFIED,
}


def category_is_certified(category: str | None) -> bool:
    if not category:
        return False
    if category in settings.certified_category_list():
        return True
    return CATEGORY_DEFAULTS.get(category, CategoryCert.NOT_CERTIFIED) is CategoryCert.CERTIFIED


def exit_is_certified(channel: str | None) -> bool:
    if not channel:
        return False
    if channel in settings.certified_exit_list() and settings.owner_override_uncertified:
        return True
    return EXIT_DEFAULTS.get(channel, CategoryCert.NOT_CERTIFIED) is CategoryCert.CERTIFIED


def current_level(*, live_sources: int, owner_sales: int, paper_closed: int, real_purchases: int) -> CertificationLevel:
    if real_purchases >= 20 and paper_closed >= 30:
        return CertificationLevel.LEVEL_5_REAL_MONEY
    if real_purchases >= 3:
        return CertificationLevel.LEVEL_4_SMALL_MONEY
    if paper_closed >= 10:
        return CertificationLevel.LEVEL_3_PAPER_TRADE
    if owner_sales >= 15:
        return CertificationLevel.LEVEL_2_MARKET_VALIDATED
    if live_sources >= 1:
        return CertificationLevel.LEVEL_1_LIVE_DATA
    return CertificationLevel.LEVEL_0_ENGINEERING
