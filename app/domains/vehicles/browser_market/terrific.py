"""Terrific.ie public stock cards. Repayment text is not the cash price."""

from __future__ import annotations

import re
from decimal import Decimal
from urllib.parse import urljoin

from app.domains.vehicles.browser_market.base import ListingCard

SOURCE_ID = "dealer-terrific"
_CARD = re.compile(
    r'carlistings__car_price"[^>]*>\s*(?:€|&euro;)?\s*([0-9][0-9,]*)\s*</div>(.{0,2500}?)<h2[^>]*>\s*<a href="([^"]+)"[^>]*>(.*?)</a>',
    re.S,
)
_PASSENGER = re.compile(r"\b(?:life|tourneo|kombi|crew|7\s*seat|seven\s*seat|wav|mpv|tipper|dropside)\b", re.I)
_MILES = re.compile(r"([\d,]+)\s*km", re.I)
_PLUS = re.compile(r"([\d,]+\s*Plus\s+Vat)", re.I)


def parse_terrific(html: str, page_url: str) -> list[ListingCard]:
    cards: list[ListingCard] = []
    seen: set[str] = set()
    for match in _CARD.finditer(html):
        price_raw, _gap, href, title_html = match.group(1), match.group(2), match.group(3), match.group(4)
        if "pm" in _gap.lower() and "car_price" not in _gap.lower():
            pass
        title = re.sub(r"<[^>]+>", "", title_html)
        title = re.sub(r"\s+", " ", title).strip()
        if _PASSENGER.search(title):
            continue
        url = urljoin(page_url, href)
        if url in seen:
            continue
        seen.add(url)
        amount = Decimal(price_raw.replace(",", ""))
        if amount < Decimal("1500"):
            continue
        cards.append(
            ListingCard(
                url=url,
                listing_class="DEALER_LISTING",
                title=title,
                source_id=SOURCE_ID,
                year=_year(title),
                asking_price_eur=amount,
                dealer="",
                geography="ROI",
                body="PANEL",
                price_status="PRICE_PLAUSIBLE",
            )
        )
    return cards


def parse_terrific_detail(html: str, card: ListingCard) -> ListingCard:
    miles = _MILES.search(html)
    if miles and card.mileage_km is None:
        card.mileage_km = int(miles.group(1).replace(",", ""))
    plus = _PLUS.search(html)
    if plus and "inc vat" not in plus.group(1).lower():
        card.vat_classification = "VAT_EXCLUSIVE"
        card.vat_presentation = "ex_vat"
        card.vat_fragment = plus.group(1)
    return card


def _year(title: str) -> int | None:
    match = re.search(r"\b(20\d{2}|19\d{2})\b", title)
    if not match:
        return None
    year = int(match.group(1))
    return year if 1995 <= year <= 2030 else None
