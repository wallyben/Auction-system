"""Append Terrific thin-family stock to the dealer mesh. Listing price only; details for mileage and VAT."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from app.domains.vehicles.browser_market.terrific import parse_terrific, parse_terrific_detail
from app.domains.vehicles.identity import parse_listing_text

MESH = Path("artifacts/runtime/cv019/dealer_mesh_006e.json")
PAGES = [
    "https://www.terrific.ie/used-cars/makes-opel/models-combo",
    "https://www.terrific.ie/used-cars/makes-vauxhall/models-combo",
    "https://www.terrific.ie/used-cars/makes-citroen/models-berlingo",
    "https://www.terrific.ie/used-cars/makes-volkswagen/models-caddy",
    "https://www.terrific.ie/used-cars/makes-mercedes-benz/models-sprinter",
    "https://www.terrific.ie/used-cars/makes-volkswagen/models-crafter",
    "https://www.terrific.ie/used-cars/makes-peugeot/models-boxer",
    "https://www.terrific.ie/used-cars/makes-peugeot/models-partner",
    "https://www.terrific.ie/used-cars/makes-mercedes-benz/models-citan",
]


def get(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ARIE-CV"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except Exception:
        return 0, ""


def main() -> None:
    payload = json.loads(MESH.read_text(encoding="utf-8"))
    rows = payload["observations"]
    known = {item["url"] for item in rows}
    added = 0
    for page in PAGES:
        status, html = get(page)
        cards = parse_terrific(html, page) if html else []
        kept = [card for card in cards if card.year and 2016 <= card.year <= 2024]
        enriched = 0
        for card in kept:
            if enriched >= 12:
                break
            detail_status, detail = get(card.url)
            if detail_status == 200 and detail:
                parse_terrific_detail(detail, card)
                enriched += 1
            identity = parse_listing_text(card.title)
            if identity.body and identity.body.value not in {"PANEL", "UNKNOWN"}:
                continue
            if card.url in known:
                continue
            known.add(card.url)
            rows.append(
                {
                    "url": card.url,
                    "title": card.title,
                    "family": identity.model_family or "",
                    "year": card.year,
                    "mileage_km": card.mileage_km,
                    "price": str(card.asking_price_eur),
                    "vat": card.vat_classification,
                    "vat_fragment": card.vat_fragment,
                    "dealer": card.dealer,
                    "source": card.source_id,
                    "body": "PANEL",
                }
            )
            added += 1
        print(page, status, "cards", len(cards), "kept", len(kept), "enriched", enriched)
    MESH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("added", added, "total", len(rows))


if __name__ == "__main__":
    main()
