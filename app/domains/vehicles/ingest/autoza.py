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

PARSER_VERSION = "autoza-vehicles-2"
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
        advertised_price_eur=price,
        vat_classification="UNKNOWN",
        source_updated_at=str(row.get("updated_at") or "") or None,
    )


def _eur_price(value: object, currency: str) -> Decimal | None:
    if currency != "EUR":
        return None
    amount = _decimal(value)
    if amount is None or amount <= 0:
        return None
    return amount


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


DETAIL_URL = "https://autoza.ie/api/v1/vehicles/{listing_id}"
MAX_INVENTORY_PAGES = 6
MAX_DETAIL_LOOKUPS = 180


@dataclass(frozen=True, slots=True)
class InventoryFetch:
    observations: tuple[MarketObservation, ...]
    rows_received: int
    rows_accepted: int
    rows_rejected: int
    rejection_reasons: dict[str, int]
    pages: int
    complete: bool
    details_fetched: int
    error: str = ""


def apply_detail(observation: MarketObservation, payload: dict[str, Any]) -> MarketObservation:
    """VAT and dealer name from the documented detail resource. Descriptions are not stored."""

    from app.domains.vehicles.vat_text import classify_vat_text, price_basis

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    description = str(data.get("description") or "")
    reading = classify_vat_text(observation.listing_title or "", description)
    seller = data.get("seller") if isinstance(data.get("seller"), dict) else {}
    dealer = str(seller.get("name") or "").strip() or None
    net, gross, rate = price_basis(observation.advertised_price_eur or observation.asking_price_eur, reading.classification, reading.fragment)
    updated = str(data.get("updated_at") or observation.source_updated_at or "") or None
    return replace(
        observation,
        dealer_name=dealer or observation.dealer_name,
        vat_presentation=reading.presentation(),
        vat_classification=reading.classification,
        vat_fragment=reading.fragment,
        vat_parser_version=reading.parser_version,
        vat_confidence=reading.confidence,
        net_price_eur=net,
        gross_price_eur=gross,
        vat_rate=rate,
        source_updated_at=updated,
        engine=str(data.get("engine_size") or observation.engine or "") or observation.engine,
    )


async def fetch_van_inventory(
    client: httpx.AsyncClient,
    *,
    observed_at: datetime | None = None,
    pause_seconds: float = PAUSE_SECONDS,
    prior: list[MarketObservation] | None = None,
) -> InventoryFetch:
    """Page body_type=van, then detail only commercial rows whose VAT text is not cached."""

    moment = observed_at or datetime.now(timezone.utc)
    received = 0
    rejected: dict[str, int] = {}
    accepted: list[MarketObservation] = []
    pages = 0
    complete = True
    error = ""
    for page in range(1, MAX_INVENTORY_PAGES + 1):
        if page > 1 and pause_seconds:
            await asyncio.sleep(pause_seconds)
        try:
            _response, payload = await request_json(
                client,
                "GET",
                SEARCH_URL,
                params={"body_type": "van", "page": str(page), "limit": str(PAGE_LIMIT)},
            )
        except (RateLimitError, SourceHttpError, httpx.HTTPError, ValueError) as exc:
            error = str(exc)
            complete = False
            _HEALTH["status"] = "DEGRADED" if accepted else "DOWN"
            _HEALTH["last_failure_at"] = moment.isoformat()
            _HEALTH["last_error"] = error
            break
        pages += 1
        if not isinstance(payload, dict):
            error = "Autoza search did not return a JSON object."
            complete = False
            break
        data = payload.get("data") or []
        received += len(data)
        for row in data:
            if not isinstance(row, dict):
                rejected["not_an_object"] = rejected.get("not_an_object", 0) + 1
                continue
            mapped = _one(row, moment)
            if mapped is None:
                rejected["not_a_recognised_commercial_van"] = rejected.get("not_a_recognised_commercial_van", 0) + 1
                continue
            accepted.append(mapped)
        meta = payload.get("meta") or {}
        total = int(meta["total"]) if isinstance(meta, dict) and meta.get("total") is not None else None
        if not data or (total is not None and received >= total) or len(data) < PAGE_LIMIT:
            complete = True
            break
    else:
        complete = False
    details = 0
    enriched: list[MarketObservation] = []
    if not error:
        enriched, details, detail_error = await _enrich(client, accepted, prior or [], pause_seconds, moment)
        if detail_error:
            error = detail_error
            complete = False
    else:
        enriched = accepted
    if not error:
        _HEALTH["status"] = "LIVE"
        _HEALTH["last_success_at"] = moment.isoformat()
        _HEALTH["last_error"] = ""
        _HEALTH["observation_count"] = len(enriched)
        _HEALTH["rows_received"] = received
        _HEALTH["rows_accepted"] = len(enriched)
        _HEALTH["rows_rejected"] = received - len(accepted)
    return InventoryFetch(
        observations=tuple(enriched),
        rows_received=received,
        rows_accepted=len(enriched),
        rows_rejected=max(0, received - len(accepted)),
        rejection_reasons=rejected,
        pages=pages,
        complete=complete and not error,
        details_fetched=details,
        error=error,
    )


async def _enrich(
    client: httpx.AsyncClient,
    rows: list[MarketObservation],
    prior: list[MarketObservation],
    pause_seconds: float,
    moment: datetime,
) -> tuple[list[MarketObservation], int, str]:
    cached: dict[str, MarketObservation] = {}
    for item in prior:
        if item.source == SOURCE_ID and item.vat_classification != "UNKNOWN":
            cached[item.listing_id] = item
    enriched: list[MarketObservation] = []
    fetched = 0
    error = ""
    for row in rows:
        previous = cached.get(row.listing_id)
        if (
            previous is not None
            and previous.source_updated_at
            and previous.source_updated_at == row.source_updated_at
        ):
            enriched.append(
                replace(
                    row,
                    dealer_name=previous.dealer_name,
                    vat_presentation=previous.vat_presentation,
                    vat_classification=previous.vat_classification,
                    vat_fragment=previous.vat_fragment,
                    vat_parser_version=previous.vat_parser_version,
                    vat_confidence=previous.vat_confidence,
                    net_price_eur=previous.net_price_eur,
                    gross_price_eur=previous.gross_price_eur,
                    vat_rate=previous.vat_rate,
                )
            )
            continue
        if fetched >= MAX_DETAIL_LOOKUPS:
            enriched.append(row)
            continue
        if fetched and pause_seconds:
            await asyncio.sleep(pause_seconds)
        listing_uuid = row.listing_id.removeprefix("autoza:")
        try:
            _response, payload = await request_json(client, "GET", DETAIL_URL.format(listing_id=listing_uuid))
        except (RateLimitError, SourceHttpError, httpx.HTTPError, ValueError) as exc:
            error = str(exc)
            _HEALTH["status"] = "DEGRADED"
            _HEALTH["last_failure_at"] = moment.isoformat()
            _HEALTH["last_error"] = error
            enriched.append(row)
            enriched.extend(rows[len(enriched) :])
            break
        fetched += 1
        try:
            if isinstance(payload, dict):
                enriched.append(apply_detail(row, payload))
            else:
                enriched.append(row)
        except Exception as exc:  # noqa: BLE001 — one bad detail must not drop the inventory
            error = str(exc)
            _HEALTH["status"] = "DEGRADED"
            _HEALTH["last_error"] = error
            enriched.append(row)
    return enriched, fetched, error

