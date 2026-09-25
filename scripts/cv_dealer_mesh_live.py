"""Live HTTP proof and thin-family capture for Windsor, CarsIreland dealers, and Linders."""

from __future__ import annotations

import json
import urllib.request
from decimal import Decimal
from pathlib import Path

from app.domains.vehicles.browser_market.carsireland_dealer import (
    matches_platform,
    parse_carsireland_dealer,
    parse_carsireland_detail,
)
from app.domains.vehicles.browser_market.linders import parse_linders, parse_linders_detail
from app.domains.vehicles.browser_market.windsor import parse_windsor
from app.domains.vehicles.browser_market.playwright_runtime import BrowserSession
from app.domains.vehicles.identity import parse_listing_text

OUT = Path("artifacts/runtime/cv019/dealer_mesh_006e.json")
THIN = ("combo", "berlingo", "caddy", "sprinter", "crafter", "citan", "boxer", "partner", "doblo", "daily", "custom", "connect", "movano")
SITES = [
    ("windsor", "https://www.windsor.ie/used-vans", "windsor"),
    ("windsor-peugeot", "https://www.windsor.ie/used-vans/peugeot", "windsor"),
    ("windsor-citroen", "https://www.windsor.ie/used-vans/citroen", "windsor"),
    ("windsor-vw", "https://www.windsor.ie/used-vans/volkswagen", "windsor"),
    ("windsor-mercedes", "https://www.windsor.ie/used-vans/mercedes-benz", "windsor"),
    ("windsor-opel", "https://www.windsor.ie/used-vans/opel", "windsor"),
    ("windsor-combo", "https://www.windsor.ie/used-vans/opel/combo", "windsor"),
    ("linnane", "https://www.johnlinnanecommercials.ie/", "carsireland"),
    ("windsor-vauxhall", "https://www.windsor.ie/used-vans/vauxhall", "windsor"),
    ("m3", "https://www.m3vancentre.ie/", "carsireland"),
    ("m3-stock", "https://www.m3vancentre.ie/used-cars/", "carsireland"),
    ("leinster", "https://www.leinstercommercials.ie/", "carsireland"),
    ("leinster-stock", "https://www.leinstercommercials.ie/used-cars/", "carsireland"),
    ("tcs", "https://www.tcstradesales.ie/", "carsireland"),
    ("linders", "https://www.linders.ie/search-vans", "linders"),
]


def get(url: str) -> tuple[int, str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ARIE-CV"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8", "replace"), ""
    except Exception as exc:
        code = getattr(exc, "code", 0)
        return int(code or 0), "", type(exc).__name__


def thin(title: str) -> bool:
    folded = title.casefold()
    return any(token in folded for token in THIN)


def row(card, family: str) -> dict:
    return {
        "url": card.url,
        "title": card.title,
        "family": family,
        "year": card.year,
        "mileage_km": card.mileage_km,
        "price": str(card.asking_price_eur) if card.asking_price_eur is not None else None,
        "vat": card.vat_classification,
        "vat_fragment": card.vat_fragment,
        "dealer": card.dealer,
        "source": card.source_id,
        "body": card.body,
    }


def main() -> None:
    report = []
    observations = []
    browser = BrowserSession()
    for name, url, kind in SITES:
        status, html, error = get(url)
        access = "HTTP"
        if kind == "windsor":
            cards = parse_windsor(html, url) if html else []
        elif kind == "linders":
            cards = parse_linders(html, url) if html else []
        else:
            cards = parse_carsireland_dealer(html, url) if html and (matches_platform(html) or "car-details/?" in html) else []
            if len(cards) < 3:
                fetched = browser.fetch(url)
                status = fetched.status_code or status
                access = "PLAYWRIGHT"
                error = fetched.challenge or fetched.error or error
                html = fetched.html
                cards = parse_carsireland_dealer(html, url) if html else []
        enriched = 0
        for card in cards:
            if not thin(card.title) or card.asking_price_eur:
                continue
            if enriched >= 25:
                break
            detail_status, detail, _detail_error = get(card.url)
            if detail_status != 200 or not detail:
                continue
            if kind == "linders":
                parse_linders_detail(detail, card)
            else:
                parse_carsireland_detail(detail, card.url, card)
            enriched += 1
        accepted = []
        for card in cards:
            if not card.asking_price_eur or card.asking_price_eur < Decimal("1500"):
                continue
            identity = parse_listing_text(card.title)
            family = identity.model_family or card.model_family
            if not family or not thin(f"{card.title} {family}"):
                continue
            if identity.body and identity.body.value not in {"PANEL", "UNKNOWN"}:
                continue
            accepted.append(row(card, family))
        observations.extend(accepted)
        report.append(
            {
                "name": name,
                "url": url,
                "status": status,
                "access": access,
                "error": error,
                "platform": matches_platform(html) if html else False,
                "cards": len(cards),
                "accepted": len(accepted),
                "vat_explicit": sum(1 for item in accepted if item["vat"] == "VAT_EXCLUSIVE"),
                "mileage": sum(1 for item in accepted if item["mileage_km"]),
                "enriched": enriched,
                "families": sorted({item["family"] for item in accepted}),
            }
        )
        print(name, status, "cards", len(cards), "accepted", len(accepted), "vat", report[-1]["vat_explicit"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    browser.close()
    OUT.write_text(json.dumps({"report": report, "observations": observations}, indent=2), encoding="utf-8")
    print("wrote", OUT, "observations", len(observations))


if __name__ == "__main__":
    main()
