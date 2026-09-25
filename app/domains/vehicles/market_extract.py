"""Deterministic listing evidence from search snippets and archived text.

A search hit is not a comparable. Price, year, and mileage are taken only from
explicit fragments. Missing attributes stay null.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from urllib.parse import urlparse

from app.domains.vehicles.vat_text import classify_vat_text

PARSER_VERSION = "market-extract-1"

_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_PRICE = re.compile(
    r"(?:€|eur|euro)\s*([0-9]{1,3}(?:[,\s][0-9]{3})+|[0-9]{3,6})(?:\.\d{2})?",
    re.I,
)
_PRICE_PREFIX = re.compile(
    r"([0-9]{1,3}(?:[,\s][0-9]{3})+|[0-9]{4,6})\s*(?:€|eur)\b",
    re.I,
)
_NOT_FULL = re.compile(
    r"\b(?:per\s+week|per\s+month|weekly|monthly|finance|deposit|lease|leasing|poa|"
    r"price\s+on\s+application|from\s+€|from\s+eur)\b",
    re.I,
)
_MILEAGE = re.compile(
    r"\b([0-9]{1,3}(?:[,\s][0-9]{3})+|[0-9]{2,7})\s*(km|kms|kilometres|kilometers|miles|mi)\b",
    re.I,
)
_ENGINE = re.compile(r"\b\d\.\d\s*(?:tdi|tdci|dci|hdi|cdti|litre|liter)\b", re.I)
_ROI = re.compile(
    r"\b(?:dublin|cork|galway|limerick|waterford|kilkenny|wexford|wicklow|kildare|"
    r"meath|louth|donegal|kerry|clare|tipperary|mayo|sligo|republic of ireland|co\.?\s+dublin)\b",
    re.I,
)
_NI = re.compile(r"\b(?:belfast|northern ireland|derry|lisburn|newry|antrim|co\.?\s+antrim)\b", re.I)
_GB = re.compile(r"\b(?:england|scotland|wales|london|manchester|birmingham|united kingdom)\b", re.I)
_SPECIAL_BODY = (
    ("tipper", "TIPPER"),
    ("dropside", "DROPSIDE"),
    ("drop side", "DROPSIDE"),
    ("luton", "LUTON"),
    ("fridge", "REFRIGERATED"),
    ("refrigerat", "REFRIGERATED"),
    ("crew", "CREW"),
    ("double cab", "CREW"),
    ("minibus", "MINIBUS"),
    ("motorhome", "MOTORHOME"),
    ("pickup", "PICKUP"),
    ("pick-up", "PICKUP"),
    ("chassis", "CHASSIS"),
    ("box van", "BOX"),
    ("panel", "PANEL"),
)
_ARTICLE = re.compile(r"\b(?:forum|review|guide|valuation|parts|wanted|breaking|spares)\b", re.I)


@dataclass(slots=True)
class ExtractedListing:
    url: str
    listing_class: str
    title: str
    year: int | None = None
    year_evidence: str = ""
    price_eur: Decimal | None = None
    price_evidence: str = ""
    price_status: str = "PRICE_UNKNOWN"
    mileage_km: int | None = None
    mileage_unit: str = ""
    mileage_source_value: int | None = None
    mileage_evidence: str = ""
    vat_classification: str = "UNKNOWN"
    vat_fragment: str = ""
    vat_presentation: str = "unknown"
    geography: str = "UNKNOWN"
    geography_evidence: str = ""
    body: str = "UNKNOWN"
    dealer: str = ""
    location: str = ""
    rejection: str = ""
    evidence: dict[str, str] = field(default_factory=dict)


def classify_listing_url(url: str) -> str:
    parsed = urlparse(url or "")
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower()
    query = parsed.query.lower()
    if "donedeal.ie" in host:
        if _searchish(path, query) or not _trailing_id(path):
            return "DONEDEAL_SEARCH_PAGE" if "donedeal.ie" in host else "OTHER"
        return "DONEDEAL_LISTING"
    if "carsireland.ie" in host:
        if _searchish(path, query) or not _trailing_id(path):
            return "CARSIRELAND_SEARCH_PAGE"
        return "CARSIRELAND_LISTING"
    if "carzone.ie" in host:
        if _searchish(path, query) or not _trailing_id(path):
            return "CARZONE_SEARCH_PAGE"
        return "CARZONE_LISTING"
    if host.endswith(".ie") and _trailing_id(path):
        return "DEALER_LISTING"
    return "OTHER"


def extract_listing(url: str, title: str, *snippets: str) -> ExtractedListing:
    listing_class = classify_listing_url(url)
    text = " ".join(part for part in (title, *snippets) if part)
    row = ExtractedListing(url=url, listing_class=listing_class, title=title or "")
    if listing_class.endswith("SEARCH_PAGE") or listing_class == "OTHER":
        row.rejection = "SEARCH_RESULT_NOT_A_LISTING"
        return row
    if _ARTICLE.search(title or "") and "van" not in (title or "").lower():
        row.rejection = "SEARCH_RESULT_NOT_A_LISTING"
        return row
    year = _YEAR.search(text)
    if year:
        row.year = int(year.group(0))
        row.year_evidence = year.group(0)
    price, evidence, status = _price(text)
    row.price_eur = price
    row.price_evidence = evidence
    row.price_status = status
    miles = _mileage(text)
    if miles:
        row.mileage_source_value, row.mileage_unit, row.mileage_km, row.mileage_evidence = miles
    vat = classify_vat_text(text)
    row.vat_classification = vat.classification
    row.vat_fragment = vat.fragment
    row.vat_presentation = vat.presentation()
    geo, geo_evidence = _geography(url, text)
    row.geography = geo
    row.geography_evidence = geo_evidence
    row.body = _body(text)
    row.location = geo_evidence
    if row.year is None or row.price_status != "PRICE_PLAUSIBLE":
        row.rejection = "INSUFFICIENT_LISTING_FACTS"
    return row


def _searchish(path: str, query: str) -> bool:
    if any(token in query for token in ("words=", "make=", "search=", "q=")):
        return True
    leaf = path.rstrip("/").split("/")[-1] if path else ""
    return leaf in {"", "search", "cars", "commercials", "vans", "used-cars", "commercials-for-sale"}


def _trailing_id(path: str) -> bool:
    leaf = path.rstrip("/").split("/")[-1]
    return bool(re.fullmatch(r"\d{5,}", leaf) or re.search(r"\d{5,}", leaf))


def _price(text: str) -> tuple[Decimal | None, str, str]:
    window = text
    if _NOT_FULL.search(window):
        match = _PRICE.search(window) or _PRICE_PREFIX.search(window)
        evidence = match.group(0) if match else ""
        return None, evidence, "PRICE_NOT_FULL_ASKING"
    match = _PRICE.search(window) or _PRICE_PREFIX.search(window)
    if match is None:
        return None, "", "PRICE_UNKNOWN"
    evidence = match.group(0)
    raw = match.group(1).replace(",", "").replace(" ", "")
    amount = Decimal(raw)
    if amount in {Decimal("0"), Decimal("1"), Decimal("99")} or amount < Decimal("400"):
        return None, evidence, "PRICE_NOT_FULL_ASKING"
    if amount > Decimal("120000"):
        return amount, evidence, "PRICE_SUSPICIOUS"
    return amount, evidence, "PRICE_PLAUSIBLE"


def _mileage(text: str) -> tuple[int, str, int, str] | None:
    cleaned = _ENGINE.sub(" ", text)
    match = _MILEAGE.search(cleaned)
    if match is None:
        return None
    raw = int(match.group(1).replace(",", "").replace(" ", ""))
    unit = match.group(2).lower()
    if raw < 100:
        return None
    if unit.startswith("mi"):
        km = int(Decimal(raw) * Decimal("1.609344"))
        return raw, "miles", km, match.group(0)
    return raw, "km", raw, match.group(0)


def _geography(url: str, text: str) -> tuple[str, str]:
    if _NI.search(text):
        found = _NI.search(text)
        return "NI", found.group(0) if found else ""
    if _GB.search(text):
        found = _GB.search(text)
        return "GB", found.group(0) if found else ""
    if _ROI.search(text):
        found = _ROI.search(text)
        return "ROI", found.group(0) if found else ""
    host = urlparse(url).netloc.lower()
    if host.endswith(".ie"):
        return "ROI", "url:.ie"
    if host.endswith(".co.uk") or host.endswith(".uk"):
        return "GB", "url:.uk"
    return "UNKNOWN", ""


def _body(text: str) -> str:
    folded = text.lower()
    for token, label in _SPECIAL_BODY:
        if token in folded:
            return label
    if "van" in folded:
        return "PANEL"
    return "UNKNOWN"


def price_plausible_for_family(amount: Decimal | None, family: str) -> str:
    if amount is None:
        return "PRICE_UNKNOWN"
    floors = {
        "small": Decimal("900"),
        "medium": Decimal("1200"),
        "large": Decimal("1500"),
    }
    from app.domains.vehicles.platforms import size_class

    floor = floors.get(size_class(family), Decimal("900"))
    if amount < floor:
        return "PRICE_SUSPICIOUS"
    if amount > Decimal("90000"):
        return "PRICE_SUSPICIOUS"
    return "PRICE_PLAUSIBLE"
