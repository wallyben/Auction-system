"""Deterministic listing and results URL classes. The search page is not a van."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse

from app.domains.vehicles.market_search import FAMILIES, MarketGroup, family_label

_LISTING_ID = re.compile(r"(?:^|[/-])(\d{5,})(?:/|$|\?)")
_RESULTS_LEAF = {
    "",
    "search",
    "cars",
    "vans",
    "commercials",
    "commercial",
    "used-cars",
    "used-vans",
    "cars-for-sale",
    "vans-for-sale",
    "commercials-for-sale",
}


def classify_market_url(url: str) -> str:
    parsed = urlparse(url or "")
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower()
    query = parsed.query.lower()
    listing = bool(_LISTING_ID.search(path))
    results = _looks_like_results(path, query)
    if "donedeal.ie" in host:
        if listing and not results:
            return "DONEDEAL_LISTING"
        if "donedeal.ie" in host:
            return "DONEDEAL_RESULTS"
    if "carsireland.ie" in host:
        return "CARSIRELAND_LISTING" if listing and not results else "CARSIRELAND_RESULTS"
    if "carzone.ie" in host:
        return "CARZONE_LISTING" if listing and not results else "CARZONE_RESULTS"
    if host.endswith(".ie") and listing and not results:
        return "DEALER_LISTING"
    if host.endswith(".ie"):
        return "UNKNOWN"
    return "UNKNOWN"


def is_listing(url_class: str) -> bool:
    return url_class.endswith("_LISTING")


def _looks_like_results(path: str, query: str) -> bool:
    if any(token in query for token in ("words=", "make=", "search=", "q=", "year_from=", "yearfrom=")):
        leaf = path.rstrip("/").split("/")[-1] if path else ""
        if not _LISTING_ID.search(path) or leaf in _RESULTS_LEAF:
            return True
    leaf = path.rstrip("/").split("/")[-1] if path else ""
    return leaf in _RESULTS_LEAF or not _LISTING_ID.search(path)


def result_urls(group: MarketGroup) -> list[tuple[str, str]]:
    """Stable public search URLs. Brave discovery may add more; these stand alone."""

    spec = FAMILIES.get(group.model_family) or {}
    label = family_label(group.model_family)
    make = str(spec.get("label") or label).split()[0]
    model = label.replace(make, "", 1).strip() or label
    words = label
    year_from = str(group.year_from)
    year_to = str(group.year_to)
    donedeal = "https://www.donedeal.ie/vans?" + urlencode(
        {"words": words, "year_from": year_from, "year_to": year_to}
    )
    cars = "https://www.carsireland.ie/used-cars?" + urlencode(
        {"section": "commercial", "make": make, "model": model, "yearFrom": year_from, "yearTo": year_to}
    )
    zone = "https://www.carzone.ie/commercials/used?" + urlencode(
        {"make": make, "model": model, "yearMin": year_from, "yearMax": year_to}
    )
    return [
        ("browser-donedeal-1", donedeal),
        ("browser-carsireland-1", cars),
        ("browser-carzone-1", zone),
    ]


def same_site(left: str, right: str) -> bool:
    return urlparse(left).netloc.lower().removeprefix("www.") == urlparse(right).netloc.lower().removeprefix("www.")


def page_query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)
