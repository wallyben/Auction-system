"""One physical van is one economic observation across marketplaces."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from decimal import Decimal

from app.domains.vehicles.market import MarketObservation

_SUFFIX = re.compile(r"\b(ltd|limited|dac|t/a|trading as)\b", re.I)
_VANISH = re.compile(r"\b(van centre|vans|van center|motors|motor company)\b", re.I)


def seller_key(name: str | None) -> str:
    text = (name or "").casefold()
    text = _SUFFIX.sub(" ", text)
    text = _VANISH.sub(" ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [token for token in text.split() if token not in {"the", "and", "of"}]
    if not tokens:
        return ""
    if len(tokens) == 1 and len(tokens[0]) < 4 and not any(character.isdigit() for character in tokens[0]):
        return ""
    return " ".join(tokens[:4])


def assign_duplicate_groups(rows: list[MarketObservation]) -> list[MarketObservation]:
    """Return the same objects with cross_source_duplicate_group_id set.

    The first row in a group stays the primary economic observation. Later rows
    keep the group id so callers can drop them from the sample.
    """

    groups: list[list[MarketObservation]] = []
    for row in rows:
        placed = False
        for group in groups:
            if _same(group[0], row):
                group.append(row)
                placed = True
                break
        if not placed:
            groups.append([row])
    assigned: list[MarketObservation] = []
    for group in groups:
        group_id = _group_id(group[0])
        for row in group:
            assigned.append(_with_group(row, group_id))
    return assigned


def primary_observations(rows: list[MarketObservation]) -> list[MarketObservation]:
    seen: set[str] = set()
    kept: list[MarketObservation] = []
    for row in rows:
        key = row.cross_source_duplicate_group_id or row.observation_id
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
    return kept


def _same(left: MarketObservation, right: MarketObservation) -> bool:
    if left.registration and right.registration and _norm(left.registration) == _norm(right.registration):
        return True
    if left.model_family != right.model_family or left.year != right.year:
        return False
    if (left.body or "UNKNOWN") != (right.body or "UNKNOWN") and "UNKNOWN" not in {left.body, right.body}:
        return False
    sellers = seller_key(left.dealer_name) and seller_key(left.dealer_name) == seller_key(right.dealer_name)
    miles = _close_miles(left.mileage_km, right.mileage_km)
    prices = _close_price(left.asking_price_eur, right.asking_price_eur)
    if left.registration and right.registration:
        return False
    return bool(sellers and miles and prices)


def _close_miles(left: int | None, right: int | None) -> bool:
    if left is None or right is None:
        return False
    gap = abs(left - right)
    return gap <= 2000 or gap <= int(max(left, right) * 0.03)


def _close_price(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None or right is None or left <= 0 or right <= 0:
        return False
    return abs(left - right) / max(left, right) <= Decimal("0.04")


def _group_id(row: MarketObservation) -> str:
    seed = "|".join(
        [
            _norm(row.registration or ""),
            row.model_family,
            str(row.year or ""),
            seller_key(row.dealer_name),
            str(row.mileage_km or ""),
            str(row.asking_price_eur or ""),
        ]
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _with_group(row: MarketObservation, group_id: str) -> MarketObservation:
    return replace(row, cross_source_duplicate_group_id=group_id)


def _norm(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())
