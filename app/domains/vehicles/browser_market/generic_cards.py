"""Layered card extraction. Class names are a hint, not the only signal."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from urllib.parse import urljoin

from app.domains.vehicles.browser_market.base import ListingCard
from app.domains.vehicles.browser_market.html_tree import Node, parse_html
from app.domains.vehicles.browser_market.urls import classify_market_url, is_listing
from app.domains.vehicles.identity import parse_listing_text
from app.domains.vehicles.market_extract import _body, _geography, _mileage, _price
from app.domains.vehicles.vat_text import classify_vat_text

_NOISE = re.compile(
    r"\b(?:sell your|finance this|weekly from|per week|per month|monthly payment|"
    r"cookie|sign in|filters|sort by)\b",
    re.I,
)
_FINANCE_SENTENCE = re.compile(
    r"\b(?:per\s+week|per\s+month|weekly|monthly payment|finance|deposit|lease|leasing|"
    r"poa|price on application|apr)\b",
    re.I,
)
_WB = re.compile(r"\b(L[1-4]|SWB|MWB|LWB)\b", re.I)
_ROOF = re.compile(r"\b(low roof|medium roof|high roof|h1|h2|h3)\b", re.I)
_FUEL = re.compile(r"\b(diesel|petrol|electric|hybrid|phev)\b", re.I)
_TRANS = re.compile(r"\b(manual|automatic|dsg)\b", re.I)


def extract_cards(html: str, page_url: str, source_id: str) -> list[ListingCard]:
    root = parse_html(html)
    cards = _from_json_ld(root, page_url, source_id)
    seen = {card.url for card in cards}
    for anchor in _listing_anchors(root, page_url):
        if anchor["url"] in seen:
            continue
        card_node = _card_ancestor(anchor["node"])
        if card_node is None:
            continue
        card = _from_text(anchor["url"], card_node.text(), source_id, anchor.get("title") or "")
        cards.append(card)
        seen.add(card.url)
    return cards


def _listing_anchors(root: Node, page_url: str) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for node in root.walk():
        if node.tag != "a" or not node.attr("href"):
            continue
        url = urljoin(page_url, node.attr("href"))
        url_class = classify_market_url(url)
        if not is_listing(url_class):
            continue
        found.append({"node": node, "url": url.split("#")[0], "title": node.text()})
    return found


def _card_ancestor(anchor: Node) -> Node | None:
    node: Node | None = anchor
    depth = 0
    while node is not None and node.tag != "document" and depth < 8:
        if node.tag in {"nav", "header", "footer", "form"}:
            return None
        text = node.text()
        if _score(node) >= 3 and ("€" in text or "eur" in text.lower()):
            return node
        node = node.parent
        depth += 1
    return None


def _score(node: Node) -> int:
    if node.tag in {"nav", "header", "footer", "form"}:
        return 0
    text = node.text()
    if not text or _NOISE.search(text) and "€" not in text and "eur" not in text.lower():
        return 0
    score = 0
    if any(child.tag == "a" and child.attr("href") for child in node.walk()):
        score += 1
    folded = text.lower()
    if "€" in text or "eur" in folded:
        score += 2
    if re.search(r"\b20\d{2}\b", text):
        score += 1
    if re.search(r"\b\d[\d,\s]{2,}\s*(?:km|miles|mi)\b", text, re.I):
        score += 1
    if re.search(r"\b(?:transit|custom|connect|partner|combo|berlingo|caddy|sprinter|crafter|van)\b", folded):
        score += 1
    if len(text) > 1200:
        score -= 2
    return score


def _from_text(url: str, text: str, source_id: str, title: str) -> ListingCard:
    url_class = classify_market_url(url)
    price_text = _without_finance(text)
    identity = parse_listing_text(title or text[:240], text)
    year = identity.year
    if year is None:
        found = re.search(r"\b(19|20)\d{2}\b", text)
        year = int(found.group(0)) if found else None
    price, evidence, status = _price(price_text)
    if price is not None and year and int(price) == year:
        price, status = None, "PRICE_NOT_FULL_ASKING"
    miles = _mileage(text)
    vat = classify_vat_text(text)
    geo, geo_evidence = _geography(url, text)
    card = ListingCard(
        url=url,
        listing_class=url_class,
        title=(title or text[:160]).strip(),
        source_id=source_id,
        manufacturer=identity.manufacturer or "",
        model_family=identity.model_family or "",
        year=year,
        asking_price_eur=price,
        currency="EUR" if price is not None else "",
        price_evidence=evidence,
        price_status=status,
        vat_classification=vat.classification if vat.classification != "UNKNOWN" else "VAT_UNKNOWN",
        vat_fragment=vat.fragment,
        vat_presentation=vat.presentation(),
        geography=geo,
        geography_evidence=geo_evidence,
        location=geo_evidence,
        body=_body(text),
        engine=_engine(text),
        fuel=(_FUEL.search(text).group(1).upper() if _FUEL.search(text) else ""),
        transmission=(_TRANS.search(text).group(1).upper() if _TRANS.search(text) else ""),
        wheelbase=(_WB.search(text).group(1).upper() if _WB.search(text) else ""),
        roof=(_ROOF.search(text).group(1).lower() if _ROOF.search(text) else ""),
    )
    if miles:
        card.mileage_unit = miles[1]
        card.mileage_km = miles[2]
        card.mileage_evidence = miles[3]
    if card.year is None or card.price_status != "PRICE_PLAUSIBLE":
        card.rejection = "INSUFFICIENT_LISTING_FACTS"
    if not is_listing(url_class):
        card.rejection = "SEARCH_PAGE_NOT_A_VEHICLE"
    card.evidence = {
        "price": card.price_evidence,
        "vat": card.vat_fragment,
        "mileage": card.mileage_evidence,
        "year": str(card.year or ""),
        "body": card.body,
    }
    return card


def _without_finance(text: str) -> str:
    cleaned = re.sub(
        r"(?:finance|deposit|lease|leasing|apr)[^€\n]{0,24}€?\s*[\d,.]+(?:\s*(?:per\s+(?:week|month)|p/?m))?",
        " ",
        text,
        flags=re.I,
    )
    cleaned = re.sub(r"€\s*[\d,.]+\s*(?:per\s+(?:week|month)|p/?m)\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\b(?:poa|price on application)\b", " ", cleaned, flags=re.I)
    return " ".join(cleaned.split()) or text


def _engine(text: str) -> str:
    match = re.search(r"\b\d\.\d\s*(?:tdi|tdci|dci|hdi|cdti|ecoblue|bluehdi)?\b", text, re.I)
    return match.group(0) if match else ""


def _from_json_ld(root: Node, page_url: str, source_id: str) -> list[ListingCard]:
    cards: list[ListingCard] = []
    for node in root.walk():
        if node.tag != "script" or "ld+json" not in node.attr("type").lower():
            continue
        raw = " ".join(node.text_parts)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for item in _json_items(payload):
            url = str(item.get("url") or "")
            if url and not url.startswith("http"):
                url = urljoin(page_url, url)
            if not url or not is_listing(classify_market_url(url)):
                continue
            offers = item.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price_raw = offers.get("price") if isinstance(offers, dict) else None
            name = str(item.get("name") or "")
            bits = [name, str(item.get("vehicleModelDate") or ""), str(price_raw or "")]
            mileage = item.get("mileageFromOdometer") or {}
            if isinstance(mileage, dict) and mileage.get("value"):
                unit = str(mileage.get("unitCode") or "KMT")
                bits.append(f"{mileage.get('value')} {'km' if unit in {'KMT', 'KM'} else 'miles'}")
            text = " ".join(bits)
            card = _from_text(url, text, source_id, name)
            if isinstance(offers, dict) and price_raw and card.asking_price_eur is None:
                try:
                    amount = Decimal(str(price_raw).replace(",", ""))
                except Exception:
                    amount = None
                if amount and amount >= Decimal("400"):
                    card.asking_price_eur = amount
                    card.price_status = "PRICE_PLAUSIBLE"
                    card.currency = str(offers.get("priceCurrency") or "EUR")
                    card.rejection = "" if card.year else card.rejection
            seller = item.get("seller") or {}
            if isinstance(seller, dict):
                card.dealer = str(seller.get("name") or "")
            address = item.get("address") or (seller.get("address") if isinstance(seller, dict) else {})
            if isinstance(address, dict):
                locality = " ".join(
                    str(address.get(key) or "") for key in ("addressLocality", "addressRegion", "addressCountry")
                )
                if locality.strip():
                    card.location = locality.strip()
                    geo, evidence = _geography(url, locality)
                    card.geography = geo
                    card.geography_evidence = evidence
            if not card.rejection:
                cards.append(card)
    return cards


def _json_items(payload: object) -> list[dict]:
    if isinstance(payload, list):
        rows: list[dict] = []
        for item in payload:
            rows.extend(_json_items(item))
        return rows
    if not isinstance(payload, dict):
        return []
    kind = str(payload.get("@type") or "")
    if kind in {"ItemList", "SearchResultsPage"}:
        rows = []
        for item in payload.get("itemListElement") or []:
            rows.extend(_json_items(item))
        return rows
    if kind == "ListItem":
        return _json_items(payload.get("item"))
    if kind in {"Vehicle", "Car", "Product", "Offer"} or payload.get("name"):
        return [payload]
    graph = payload.get("@graph")
    if isinstance(graph, list):
        return _json_items(graph)
    return []
