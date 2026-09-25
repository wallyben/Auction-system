"""Owner-supplied Irish dealer stock. A URL is fetched only when the owner configured it."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from decimal import Decimal

from app.domains.vehicles.enums import Fuel, ObservationStatus
from app.domains.vehicles.market import MarketObservation

PARSER_VERSION = "dealer-feed-1"


def parse_dealer_feed(text: str, *, observed_at: datetime, source: str = "dealer_stock_feed") -> list[MarketObservation]:
    stripped = text.strip()
    if not stripped:
        return []
    if stripped[0] in "[{":
        payload = json.loads(stripped)
        rows = payload if isinstance(payload, list) else payload.get("vehicles") or payload.get("listings") or []
        return [_from_mapping(row, observed_at=observed_at, source=source, index=index) for index, row in enumerate(rows)]
    reader = csv.DictReader(io.StringIO(stripped))
    return [
        _from_mapping(row, observed_at=observed_at, source=source, index=index)
        for index, row in enumerate(reader)
    ]


def _from_mapping(row: dict, *, observed_at: datetime, source: str, index: int) -> MarketObservation:
    listing_id = str(row.get("listing_id") or row.get("id") or f"{source}-{index}")
    price = _dec(row.get("asking_price_eur") or row.get("price_eur"))
    native = _dec(row.get("price") or row.get("native_price"))
    currency = str(row.get("currency") or row.get("native_currency") or ("EUR" if price is not None else ""))
    if price is None and currency.upper() == "EUR":
        price = native
    return MarketObservation(
        observation_id=_observation_id(source, listing_id, price, observed_at),
        listing_id=listing_id,
        observed_at=observed_at,
        manufacturer=str(row.get("manufacturer") or row.get("make") or "").lower(),
        model_family=str(row.get("model_family") or row.get("model") or "").lower().replace(" ", "_"),
        year=_int(row.get("year")),
        fuel=_fuel(str(row.get("fuel") or "")),
        body=str(row.get("body") or "UNKNOWN").upper(),
        wheelbase=_lower(row.get("wheelbase")),
        roof=_lower(row.get("roof")),
        transmission=_lower(row.get("transmission")),
        derivative=_lower(row.get("derivative")),
        mileage_km=_int(row.get("mileage_km") or row.get("mileage")),
        generation=_lower(row.get("generation")),
        asking_price_eur=price,
        realised_price_eur=_dec(row.get("realised_price_eur")),
        seller_type=str(row.get("seller_type") or "dealer"),
        vat_presentation=str(row.get("vat_presentation") or "unknown"),
        location=str(row.get("location") or ""),
        status=ObservationStatus(str(row.get("status") or "ACTIVE")),
        source=str(row.get("source") or source),
        url=row.get("url"),
        registration=_upper(row.get("registration")),
        engine=_lower(row.get("engine")),
        listing_title=row.get("title"),
        native_price=native,
        native_currency=currency or None,
        parser_version=PARSER_VERSION,
    )


def _observation_id(source: str, listing_id: str, price: Decimal | None, observed_at: datetime) -> str:
    stamp = observed_at.strftime("%Y%m%d%H%M")
    amount = "none" if price is None else str(price)
    raw = f"{source}:{listing_id}:{amount}:{stamp}"
    return raw[:64]


def _dec(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value).replace(",", "").replace("€", "").strip())


def _int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(str(value).replace(",", "").split(".")[0])


def _fuel(value: str) -> Fuel:
    try:
        return Fuel(value.upper())
    except ValueError:
        folded = value.lower()
        if "diesel" in folded:
            return Fuel.DIESEL
        if "electric" in folded:
            return Fuel.ELECTRIC
        return Fuel.UNKNOWN


def _lower(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value).lower()


def _upper(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value).upper()
