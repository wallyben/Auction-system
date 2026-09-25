"""Windsor public used-van stock. JSON-LD plus the per-card Price Ex VAT tag."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from urllib.parse import urljoin

from app.domains.vehicles.browser_market.base import ListingCard

SOURCE_ID = "dealer-windsor"
_PASSENGER = re.compile(r"\b(?:life|tourneo|kombi|crew|7\s*seat|seven\s*seat|wav|mpv|tipper|dropside)\b", re.I)


def parse_windsor(html: str, page_url: str) -> list[ListingCard]:
    ex_vat_urls = _ex_vat_urls(html)
    cards: list[ListingCard] = []
    for item in _jsonld_items(html):
        if item.get("@type") not in {"Car", "Vehicle", "Product"}:
            continue
        url = str(item.get("url") or "")
        if not url:
            continue
        url = urljoin(page_url, url.split("#")[0])
        name = str(item.get("name") or "")
        model = str(item.get("model") or "")
        if _PASSENGER.search(f"{name} {model}"):
            continue
        price = _price(item.get("offers") or item)
        if price is None:
            continue
        year = _year(item.get("vehicleModelDate"))
        mileage = _mileage(item.get("mileageFromOdometer"))
        exclusive = url in ex_vat_urls
        cards.append(
            ListingCard(
                url=url,
                listing_class="DEALER_LISTING",
                title=name,
                source_id=SOURCE_ID,
                manufacturer=(name.split() or [""])[0].lower(),
                model_family=model.lower().replace(" ", "_"),
                year=year,
                mileage_km=mileage,
                asking_price_eur=price,
                vat_classification="VAT_EXCLUSIVE" if exclusive else "UNKNOWN",
                vat_presentation="ex_vat" if exclusive else "unknown",
                vat_fragment="Price Ex VAT" if exclusive else "",
                body="PANEL",
                geography="ROI",
                dealer="Windsor",
                registration=_registration(url),
                price_status="PRICE_PLAUSIBLE",
            )
        )
    return cards


def _ex_vat_urls(html: str) -> set[str]:
    urls: set[str] = set()
    for chunk in re.split(r"vehicleCard__tagContainer", html):
        if "price ex vat" not in chunk.lower():
            continue
        match = re.search(r'href="(/vehicle-details/[^"]+)"', chunk)
        if match:
            urls.add("https://www.windsor.ie" + match.group(1))
    return urls


def _jsonld_items(html: str) -> list[dict]:
    found: list[dict] = []
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        _walk(payload, found)
    return found


def _walk(payload: object, found: list[dict]) -> None:
    if isinstance(payload, list):
        for item in payload:
            _walk(item, found)
        return
    if not isinstance(payload, dict):
        return
    if payload.get("@type") in {"Car", "Vehicle", "Product"} and payload.get("url"):
        found.append(payload)
    for value in payload.values():
        if isinstance(value, (dict, list)):
            _walk(value, found)


def _price(node: object) -> Decimal | None:
    if isinstance(node, dict):
        if "price" in node:
            return _decimal(node.get("price"))
        return _price(node.get("offers"))
    return None


def _decimal(value: object) -> Decimal | None:
    try:
        amount = Decimal(str(value))
    except Exception:
        return None
    if amount <= 0 or amount > Decimal("200000"):
        return None
    return amount.quantize(Decimal("0.01"))


def _registration(url: str) -> str:
    match = re.search(r"/(\d{2,3}[a-z]{1,2}\d+)-", url, re.I)
    return match.group(1).upper() if match else ""


def _year(value: object) -> int | None:
    try:
        year = int(str(value)[:4])
    except (TypeError, ValueError):
        return None
    return year if 1990 <= year <= 2030 else None


def _mileage(value: object) -> int | None:
    if isinstance(value, dict):
        value = value.get("value")
    try:
        km = int(value)
    except (TypeError, ValueError):
        return None
    return km if 0 < km < 1_000_000 else None
