"""Linders public van stock. Cash price is Our Price, never the monthly finance figure."""

from __future__ import annotations

import re
from decimal import Decimal
from urllib.parse import urljoin

from app.domains.vehicles.browser_market.base import ListingCard

SOURCE_ID = "dealer-linders"
_TILE = re.compile(r'<div class="car-tile">(.*?)</div>\s*</div>\s*</div>', re.S)
_HREF = re.compile(r'href="(/vehicle\?id=[^"#]+)"')
_TITLE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S)
_PRICE = re.compile(r"Our Price\s*</p>\s*<h3>\s*(?:&euro;|€)\s*([0-9][0-9,]*)", re.I)
_MILES = re.compile(r"(\d{1,3}(?:,\d{3})*|\d+)\s*KMS", re.I)
_VAT = re.compile(r"(\d[\d,]*\s*\+\s*23%\s*Vat)", re.I)
_PASSENGER = re.compile(r"\b(?:life|tourneo|kombi|crew|7\s*seat|seven\s*seat|wav|mpv|tipper|dropside)\b", re.I)


def parse_linders(html: str, page_url: str) -> list[ListingCard]:
    cards: list[ListingCard] = []
    seen: set[str] = set()
    for match in _HREF.finditer(html):
        url = urljoin(page_url, match.group(1))
        if url in seen:
            continue
        seen.add(url)
        window = html[match.start() : match.start() + 1800]
        title_match = _TITLE.search(window)
        title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""
        if not title or _PASSENGER.search(title):
            continue
        year = _year(title)
        cards.append(
            ListingCard(
                url=url,
                listing_class="DEALER_LISTING",
                title=title,
                source_id=SOURCE_ID,
                year=year,
                dealer="Linders",
                geography="ROI",
                body="PANEL",
                price_status="PRICE_UNKNOWN",
            )
        )
    return cards


def parse_linders_detail(html: str, card: ListingCard) -> ListingCard:
    price = _PRICE.search(html)
    if price:
        card.asking_price_eur = Decimal(price.group(1).replace(",", ""))
        card.price_status = "PRICE_PLAUSIBLE"
    miles = _MILES.search(html)
    if miles and card.mileage_km is None:
        raw = int(miles.group(1).replace(",", ""))
        card.mileage_km = raw * 1000 if raw < 1000 else raw
    vat = _VAT.search(html)
    if vat:
        card.vat_classification = "VAT_EXCLUSIVE"
        card.vat_presentation = "ex_vat"
        card.vat_fragment = vat.group(1)
    return card


def _year(title: str) -> int | None:
    match = re.match(r"(\d{4})", title)
    if not match:
        return None
    year = int(match.group(1))
    return year if 1995 <= year <= 2030 else None
