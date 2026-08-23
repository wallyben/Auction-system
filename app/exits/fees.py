"""Versioned channel fee schedules. Never apply a single 12.9% to every exit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class FeeRule:
    channel: str
    source: str
    effective_from: date
    last_verified: date
    jurisdiction: str
    category_scope: str
    percent: Decimal
    fixed_eur: Decimal
    vat_on_fee: Decimal
    payment_percent: Decimal
    payment_fixed: Decimal
    notes: str


# Publicly documented / operator-verified assumptions. Not invoices.
FEE_SCHEDULE: tuple[FeeRule, ...] = (
    FeeRule(
        "ebay_ie",
        "https://www.ebay.ie/help/selling/fees-credits-invoices/selling-fees",
        date(2025, 1, 1),
        date(2026, 8, 23),
        "IE",
        "most_categories",
        Decimal("0.129"),
        Decimal("0.35"),
        Decimal("0.23"),
        Decimal("0.019"),
        Decimal("0.25"),
        "eBay IE final value + VAT on fee. Confirm current seller rate card.",
    ),
    FeeRule(
        "ebay_gb",
        "https://www.ebay.co.uk/help/selling/fees-credits-invoices/selling-fees",
        date(2025, 1, 1),
        date(2026, 8, 23),
        "GB",
        "most_categories",
        Decimal("0.129"),
        Decimal("0.30"),
        Decimal("0.20"),
        Decimal("0.019"),
        Decimal("0.20"),
        "eBay GB. Sterling exit; convert after fees. VAT on fee is UK VAT.",
    ),
    FeeRule(
        "local_ie",
        "owner_classifieds",
        date(2025, 1, 1),
        date(2026, 8, 23),
        "IE",
        "all",
        Decimal("0.00"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        "DoneDeal/Adverts/collection. No platform fee; cash/Revolut risk remains.",
    ),
    FeeRule(
        "cardmarket",
        "https://www.cardmarket.com/",
        date(2025, 1, 1),
        date(2026, 8, 23),
        "EU",
        "trading_cards",
        Decimal("0.05"),
        Decimal("0.35"),
        Decimal("0.00"),
        Decimal("0.019"),
        Decimal("0.25"),
        "Cardmarket seller commission band; confirm account tier.",
    ),
    FeeRule(
        "discogs",
        "https://support.discogs.com/",
        date(2025, 1, 1),
        date(2026, 8, 23),
        "EU",
        "music",
        Decimal("0.08"),
        Decimal("0"),
        Decimal("0.00"),
        Decimal("0.029"),
        Decimal("0.30"),
        "Discogs marketplace fee + typical payment processor.",
    ),
    FeeRule(
        "reverb",
        "https://reverb.com/page/seller-fees",
        date(2025, 1, 1),
        date(2026, 8, 23),
        "EU",
        "music_dj",
        Decimal("0.05"),
        Decimal("0.25"),
        Decimal("0.00"),
        Decimal("0.029"),
        Decimal("0.30"),
        "Reverb seller fee band for most listings.",
    ),
    FeeRule(
        "cex_trade_in",
        "store_quote",
        date(2025, 1, 1),
        date(2026, 8, 23),
        "IE",
        "electronics",
        Decimal("0.00"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        "Trade-in is a bid, not a fee. Gross expected sale must already be the voucher/cash quote.",
    ),
    FeeRule(
        "auction_ie",
        "house_terms",
        date(2025, 1, 1),
        date(2026, 8, 23),
        "IE",
        "all",
        Decimal("0.15"),
        Decimal("0"),
        Decimal("0.23"),
        Decimal("0"),
        Decimal("0"),
        "Seller commission varies by house. Conservative 15% + VAT on commission.",
    ),
    FeeRule(
        "dealer",
        "owner_negotiated",
        date(2025, 1, 1),
        date(2026, 8, 23),
        "IE",
        "all",
        Decimal("0.00"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        "Dealer bid. Speed high, price typically below private sale.",
    ),
)


def fee_for(channel: str, category: str | None = None) -> FeeRule:
    matches = [rule for rule in FEE_SCHEDULE if rule.channel == channel]
    if not matches:
        return FEE_SCHEDULE[0]
    if category:
        scoped = [rule for rule in matches if rule.category_scope in {category, "all", "most_categories"}]
        if scoped:
            return scoped[0]
    return matches[0]
