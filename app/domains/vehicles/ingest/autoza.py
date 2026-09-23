"""Autoza Irish asking-price provider.

Uses the documented read-only search ``GET /api/v1/vehicles``. HTML is not fetched.
The OpenAPI document says basic search needs no key. ``body_type=van`` is a hint,
not proof that a row is a commercial van. Rows still pass the van identity parser.
Missing registration, VAT, wheelbase, and generation stay missing.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from app.core.http import RateLimitError, SourceHttpError, request_json
from app.domains.vehicles.enums import CommercialClass, Fuel, ObservationStatus
from app.domains.vehicles.identity import parse_listing_text
from app.domains.vehicles.listing_state import status_for_new_observation
from app.domains.vehicles.market import MarketBook, MarketObservation

PARSER_VERSION = "autoza-vehicles-1"
SOURCE_ID = "autoza"
SEARCH_URL = "https://autoza.ie/api/v1/vehicles"
PAGE_LIMIT = 50
MAX_PAGES_PER_QUERY = 2
PAUSE_SECONDS = 2.0
_MILES_TO_KM = Decimal("1.609344")

_HEALTH: dict[str, object] = {
    "provider": SOURCE_ID,
    "status": "NOT_RUN",
    "last_success_at": None,
    "last_failure_at": None,
    "last_error": "",
    "observation_count": 0,
    "rate_limit": "idle",
    "access": "GET https://autoza.ie/api/v1/vehicles",
}


@dataclass(frozen=True, slots=True)
class AutozaFetch:
    observations: tuple[MarketObservation, ...]
    queries: int
    pages: int
    complete: bool
    raw_pages: int
    error: str = ""


def autoza_enabled() -> bool:
    return os.environ.get("CV_AUTOZA", "1") != "0"


def autoza_health() -> dict[str, object]:
    return dict(_HEALTH)


def observations_from_search(payload: dict[str, Any], *, observed_at: datetime) -> list[MarketObservation]:
    rows = payload.get("data") or []
    observations: list[MarketObservation] = []
    for row in rows:
        if isinstance(row, dict):
            mapped = _one(row, observed_at)
            if mapped is not None:
                observations.append(mapped)
    return observations


def apply_history(book: MarketBook, rows: list[MarketObservation]) -> list[MarketObservation]:
    """Price cuts, increases, and returns are new rows. Nothing is overwritten."""

    annotated: list[MarketObservation] = []
    for row in rows:
        prior = [item for item in book.observations if item.listing_id == row.listing_id and item.source == row.source]
        status = status_for_new_observation(prior, asking_price_eur=row.asking_price_eur)
        annotated.append(replace(row, status=status))
    return annotated


async def fetch_autoza(
    client: httpx.AsyncClient,
    queries: list[dict[str, str]],
    *,
    observed_at: datetime | None = None,
    pause_seconds: float = PAUSE_SECONDS,
) -> AutozaFetch:
    moment = observed_at or datetime.now(timezone.utc)
    found: list[MarketObservation] = []
    pages = 0
    complete = True
    error = ""
    for index, query in enumerate(queries):
        if index and pause_seconds:
            await asyncio.sleep(pause_seconds)
        try:
            page_rows, page_count, query_complete = await _pages(
                client, query, moment, pause_seconds=pause_seconds
            )
        except RateLimitError as exc:
            _HEALTH["rate_limit"] = "limited"
            _HEALTH["status"] = "RATE_LIMITED"
            _HEALTH["last_failure_at"] = moment.isoformat()
            _HEALTH["last_error"] = str(exc)
            error = str(exc)
            complete = False
            break
        except (SourceHttpError, httpx.HTTPError, ValueError) as exc:
            _HEALTH["status"] = "FAILED"
            _HEALTH["last_failure_at"] = moment.isoformat()
            _HEALTH["last_error"] = str(exc)
            error = str(exc)
            complete = False
            break
        found.extend(page_rows)
        pages += page_count
        complete = complete and query_complete
    if not error:
        _HEALTH["status"] = "OK"
        _HEALTH["rate_limit"] = "ok"
        _HEALTH["last_success_at"] = moment.isoformat()
        _HEALTH["last_error"] = ""
        _HEALTH["observation_count"] = int(_HEALTH["observation_count"] or 0) + len(found)
    return AutozaFetch(
        observations=tuple(found),
        queries=len(queries),
        pages=pages,
        complete=complete and not error,
        raw_pages=pages,
        error=error,
    )


async def _pages(
    client: httpx.AsyncClient,
    query: dict[str, str],
    observed_at: datetime,
    *,
    pause_seconds: float,
) -> tuple[list[MarketObservation], int, bool]:
    collected: list[MarketObservation] = []
    total: int | None = None
    fetched = 0
    page_count = 0
    for page in range(1, MAX_PAGES_PER_QUERY + 1):
        if page > 1 and pause_seconds:
            await asyncio.sleep(pause_seconds)
        params = {
            "make": query.get("make") or "",
            "model": query.get("model") or "",
            "body_type": "van",
            "page": str(page),
            "limit": str(PAGE_LIMIT),
        }
        page_count += 1
        _response, payload = await request_json(client, "GET", SEARCH_URL, params=params)
        if not isinstance(payload, dict):
            raise ValueError("Autoza search did not return a JSON object.")
        batch = observations_from_search(payload, observed_at=observed_at)
        collected.extend(batch)
        meta = payload.get("meta") or {}
        if isinstance(meta, dict) and meta.get("total") is not None:
            total = int(meta["total"])
        fetched += len(payload.get("data") or [])
        if not payload.get("data"):
            break
        if total is not None and fetched >= total:
            break
        if len(payload.get("data") or []) < PAGE_LIMIT:
            break
    query_complete = total is None or fetched >= total
    if total is not None and fetched < total and fetched >= PAGE_LIMIT * MAX_PAGES_PER_QUERY:
        query_complete = False
    return collected, page_count, query_complete


def _one(row: dict[str, Any], observed_at: datetime) -> MarketObservation | None:
    title = " ".join(
        str(row.get(key) or "").strip()
        for key in ("year", "make", "model", "variant")
        if str(row.get(key) or "").strip()
    )
    identity = parse_listing_text(title, str(row.get("body_type") or ""))
    if identity.model_family is None:
        return None
    if identity.commercial_class in {CommercialClass.PASSENGER, CommercialClass.PARTS_OR_NOT_A_VEHICLE}:
        return None
    listing_id = str(row.get("id") or "").strip()
    if not listing_id:
        return None
    currency = str(row.get("currency") or "").upper()
    price = _eur_price(row.get("price"), currency)
    mileage = _mileage(row.get("mileage"), str(row.get("mileage_unit") or "km"))
    fuel = identity.fuel if identity.fuel is not Fuel.UNKNOWN else _fuel(str(row.get("fuel_type") or ""))
    raw = {
        "id": listing_id,
        "make": row.get("make"),
        "model": row.get("model"),
        "variant": row.get("variant"),
        "year": row.get("year"),
        "price": row.get("price"),
        "currency": row.get("currency"),
        "mileage": row.get("mileage"),
        "mileage_unit": row.get("mileage_unit"),
        "fuel_type": row.get("fuel_type"),
        "transmission": row.get("transmission"),
        "body_type": row.get("body_type"),
        "location": row.get("location"),
        "listed_at": row.get("listed_at"),
        "updated_at": row.get("updated_at"),
    }
    stamp = observed_at.strftime("%Y%m%d%H%M")
    amount = "none" if price is None else str(price)
    return MarketObservation(
        observation_id=f"autoza:{listing_id}:{amount}:{stamp}"[:64],
        listing_id=f"autoza:{listing_id}",
        observed_at=observed_at,
        manufacturer=identity.manufacturer or str(row.get("make") or "").casefold(),
        model_family=identity.model_family,
        year=_int(row.get("year")) or identity.year,
        fuel=fuel,
        body=identity.body.value,
        wheelbase=identity.wheelbase,
        roof=identity.roof,
        transmission=(str(row.get("transmission") or identity.transmission or "").casefold() or None),
        derivative=identity.derivative,
        mileage_km=mileage if mileage is not None else identity.mileage_km,
        generation=identity.generation,
        asking_price_eur=price,
        realised_price_eur=None,
        seller_type="dealer",
        vat_presentation="unknown",
        location=str(row.get("location") or ""),
        status=ObservationStatus.ACTIVE,
        source=SOURCE_ID,
        url=str(row.get("url") or "") or None,
        registration=None,
        engine=identity.engine,
        listing_title=title,
        native_price=_decimal(row.get("price")),
        native_currency=currency or None,
        parser_version=PARSER_VERSION,
        raw_reference=json.dumps(raw, default=str, separators=(",", ":"))[:4000],
        dealer_name=None,
    )


def _eur_price(value: object, currency: str) -> Decimal | None:
    if currency != "EUR":
        return None
    return _decimal(value)


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _mileage(value: object, unit: str) -> int | None:
    amount = _decimal(value)
    if amount is None:
        return None
    if unit.casefold() in {"mi", "mile", "miles"}:
        amount = amount * _MILES_TO_KM
    return int(amount)


def _fuel(text: str) -> Fuel:
    folded = text.casefold()
    if "diesel" in folded:
        return Fuel.DIESEL
    if "electric" in folded or folded == "ev":
        return Fuel.ELECTRIC
    if "plug" in folded:
        return Fuel.PHEV
    if "hybrid" in folded:
        return Fuel.HYBRID
    if "petrol" in folded:
        return Fuel.PETROL
    return Fuel.UNKNOWN
