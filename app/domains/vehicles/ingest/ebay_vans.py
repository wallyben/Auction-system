"""eBay Browse API for commercial vans. Official credentials only. Not the camera search."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.domains.vehicles.enums import ObservationStatus
from app.domains.vehicles.identity import parse_listing_text
from app.domains.vehicles.ingest.dealer_feed import _observation_id
from app.domains.vehicles.market import MarketObservation

PARSER_VERSION = "ebay-vans-1"
SOURCE_ID = "ebay_vans"
VAN_QUERIES = (
    "Ford Transit Custom panel van",
    "Volkswagen Transporter panel van",
    "Renault Trafic panel van",
    "Peugeot Expert panel van",
    "Mercedes Sprinter panel van",
    "Citroen Berlingo panel van",
)


def credentials_configured() -> bool:
    return bool(os.environ.get("EBAY_CLIENT_ID", "").strip() and os.environ.get("EBAY_CLIENT_SECRET", "").strip())


def vans_enabled() -> bool:
    return credentials_configured() and os.environ.get("CV_EBAY_VANS", "1") != "0"


def observations_from_summaries(
    items: list[dict[str, Any]],
    *,
    observed_at: datetime | None = None,
    marketplace: str = "EBAY_IE",
) -> list[MarketObservation]:
    moment = observed_at or datetime.now(timezone.utc)
    rows: list[MarketObservation] = []
    for item in items:
        title = str(item.get("title") or "")
        identity = parse_listing_text(title)
        if identity.model_family is None:
            continue
        if identity.commercial_class.value in {"PASSENGER", "PARTS_OR_NOT_A_VEHICLE"}:
            continue
        condition = str(item.get("condition") or "").lower()
        flags: tuple[str, ...] = ()
        if "part" in condition or "salvage" in title.lower() or "damaged" in title.lower():
            flags = ("for_spares",)
        price_block = item.get("price") or {}
        currency = str(price_block.get("currency") or "").upper()
        amount = Decimal(str(price_block["value"])) if price_block.get("value") not in (None, "") else None
        asking = amount if currency == "EUR" else None
        item_id = str(item.get("itemId") or item.get("item_id") or "")
        if not item_id:
            continue
        seller = item.get("seller") or {}
        location = item.get("itemLocation") or {}
        rows.append(
            MarketObservation(
                observation_id=_observation_id(SOURCE_ID, item_id, asking or amount, moment),
                listing_id=f"{SOURCE_ID}:{item_id}",
                observed_at=moment,
                manufacturer=identity.manufacturer or "",
                model_family=identity.model_family,
                year=identity.year,
                fuel=identity.fuel,
                body=identity.body.value,
                wheelbase=identity.wheelbase,
                roof=identity.roof,
                transmission=identity.transmission,
                derivative=identity.derivative,
                mileage_km=identity.mileage_km,
                generation=identity.generation,
                asking_price_eur=asking,
                realised_price_eur=None,
                seller_type="dealer" if seller else "unknown",
                vat_presentation="unknown",
                location=str(location.get("city") or location.get("country") or marketplace),
                status=ObservationStatus.ACTIVE,
                source=SOURCE_ID,
                url=item.get("itemWebUrl") or item.get("item_web_url"),
                engine=identity.engine,
                listing_title=title,
                condition_flags=flags,
                native_price=amount,
                native_currency=currency or None,
                parser_version=PARSER_VERSION,
                raw_reference=item_id,
            )
        )
    return rows
