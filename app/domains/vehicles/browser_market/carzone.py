"""Carzone public commercial search cards."""

from app.domains.vehicles.browser_market.base import ListingCard
from app.domains.vehicles.browser_market.generic_cards import extract_cards

SOURCE_ID = "browser-carzone-1"


def parse_carzone(html: str, page_url: str) -> list[ListingCard]:
    return extract_cards(html, page_url, SOURCE_ID)
