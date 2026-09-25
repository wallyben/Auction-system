"""Twelve-hour cache of a market-group page. The page body is not stored."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.domains.vehicles.browser_market.base import ListingCard


def cache_dir() -> Path:
    root = Path(os.environ.get("CV_BROWSER_STATE_DIR", "artifacts/runtime/browser_market"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def cache_hours() -> int:
    raw = os.environ.get("CV_BROWSER_CACHE_HOURS", "12")
    try:
        return max(1, int(raw))
    except ValueError:
        return 12


def _key(source_id: str, group_id: str, url: str) -> str:
    import hashlib

    return hashlib.sha256(f"{source_id}|{group_id}|{url}".encode()).hexdigest()[:24]


def load_cached(source_id: str, group_id: str, url: str, *, now: datetime | None = None) -> list[dict] | None:
    path = cache_dir() / f"{_key(source_id, group_id, url)}.json"
    if not path.exists():
        return None
    moment = now or datetime.now(timezone.utc)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    retrieved = datetime.fromisoformat(payload["retrieved_at"])
    if moment - retrieved > timedelta(hours=cache_hours()):
        return None
    return list(payload.get("cards") or [])


def store_cached(source_id: str, group_id: str, url: str, cards: list[ListingCard], *, now: datetime | None = None) -> None:
    moment = now or datetime.now(timezone.utc)
    path = cache_dir() / f"{_key(source_id, group_id, url)}.json"
    payload = {
        "source_id": source_id,
        "group_id": group_id,
        "url": url,
        "retrieved_at": moment.isoformat(),
        "cards": [_public(card) for card in cards],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_group_snapshot(rows: list[dict]) -> None:
    (cache_dir() / "groups.json").write_text(json.dumps(rows), encoding="utf-8")


def read_group_snapshot() -> list[dict]:
    path = cache_dir() / "groups.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return list(data) if isinstance(data, list) else []


def _public(card: ListingCard) -> dict:
    return {
        "url": card.url,
        "title": card.title,
        "year": card.year,
        "mileage_km": card.mileage_km,
        "asking_price_eur": str(card.asking_price_eur) if card.asking_price_eur is not None else None,
        "vat_classification": card.vat_classification,
        "vat_presentation": card.vat_presentation,
        "vat_fragment": card.vat_fragment,
        "body": card.body,
        "geography": card.geography,
        "dealer": card.dealer,
        "model_family": card.model_family,
        "manufacturer": card.manufacturer,
        "source_id": card.source_id,
        "listing_class": card.listing_class,
        "price_status": card.price_status,
        "rejection": card.rejection,
        "location": card.location,
        "fuel": card.fuel,
        "transmission": card.transmission,
    }
