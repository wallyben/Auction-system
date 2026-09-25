"""Independent dealer sites that embed CarsIreland stock cards."""

from __future__ import annotations

import re
from decimal import Decimal
from urllib.parse import urljoin

from app.domains.vehicles.browser_market.base import ListingCard
from app.domains.vehicles.vat_text import classify_vat_text

SOURCE_ID = "dealer-carsireland-site"
_DETAIL = re.compile(r'href="([^"]*?/car-details/\?(\d+)=([^"]+))"', re.I)
_OUR_PRICE = re.compile(r"Our Price\s*</span>\s*<span[^>]*>\s*€?\s*([0-9][0-9,]*)", re.I)
_PASSENGER = re.compile(r"\b(?:life|tourneo|kombi|crew|7\s*seat|seven\s*seat|wav|mpv|tipper|dropside|ranger)\b", re.I)
_MILES = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{4,6})\s*(?:km|kms|miles)", re.I)


def matches_platform(html: str) -> bool:
    folded = html.lower()
    return "carsireland" in folded and "car-details" in folded and ("our price" in folded or "powered by carsireland" in folded or "car-details__" in folded)


def parse_carsireland_dealer(html: str, page_url: str) -> list[ListingCard]:
    if not matches_platform(html) and "car-details/?" not in html:
        return []
    dealer = _dealer_name(page_url)
    cards: list[ListingCard] = []
    seen: set[str] = set()
    for match in _DETAIL.finditer(html):
        href, stock_id, slug = match.group(1), match.group(2), match.group(3)
        url = urljoin(page_url, href.split("&")[0].replace(" ", "%20"))
        if url in seen:
            continue
        seen.add(url)
        title = slug.replace("-", " ").replace("+", " ")
        title = re.sub(r"^\d{4}\s+", "", title).strip()
        if _PASSENGER.search(title):
            continue
        year = _year(slug)
        cards.append(
            ListingCard(
                url=url,
                listing_class="DEALER_LISTING",
                title=title,
                source_id=SOURCE_ID,
                year=year,
                dealer=dealer,
                geography="ROI",
                body="PANEL",
                price_status="PRICE_UNKNOWN",
                registration=stock_id,
            )
        )
    return cards


def parse_carsireland_detail(html: str, page_url: str, card: ListingCard) -> ListingCard:
    """Use Our Price. Weekly and monthly figures are not the cash price."""

    price_match = _OUR_PRICE.search(html)
    if price_match:
        card.asking_price_eur = Decimal(price_match.group(1).replace(",", ""))
        card.price_status = "PRICE_PLAUSIBLE"
    miles = _MILES.search(html)
    if miles and card.mileage_km is None:
        raw = int(miles.group(1).replace(",", ""))
        card.mileage_km = int(raw * 1.60934) if "mile" in miles.group(0).lower() else raw
    reading = classify_vat_text(html)
    if reading.classification != "UNKNOWN":
        card.vat_classification = reading.classification
        card.vat_presentation = reading.presentation()
        card.vat_fragment = reading.fragment
    elif re.search(r"price\s+ex\s+vat", html, re.I):
        card.vat_classification = "VAT_EXCLUSIVE"
        card.vat_presentation = "ex_vat"
        card.vat_fragment = "Price EX VAT"
    return card


def _year(slug: str) -> int | None:
    match = re.match(r"(\d{4})", slug)
    if not match:
        return None
    year = int(match.group(1))
    return year if 1995 <= year <= 2030 else None


def _dealer_name(page_url: str) -> str:
    host = page_url.split("/")[2] if "://" in page_url else page_url
    return host.removeprefix("www.").split(".")[0]
