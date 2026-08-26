"""Negotiation targets from economics, not arbitrary discount percentages."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.money import ZERO, money


@dataclass(slots=True)
class Negotiation:
    ask: Decimal
    ideal_offer: Decimal
    acceptable_offer: Decimal
    walk_away_price: Decimal
    notes: str


def negotiation_targets(
    *,
    ask: Decimal,
    max_buy: Decimal,
    expected_profit: Decimal,
    listing_type: str = "fixed",
) -> Negotiation:
    walk = money(max_buy)
    if listing_type == "auction":
        return Negotiation(ask, walk, walk, walk, "Auction: bid the max hammer, do not drip.")
    if walk <= ZERO:
        return Negotiation(ask, ZERO, ZERO, ZERO, "Max buy is zero. Do not offer.")
    # Ideal: leave room so even a mid outcome still clears target profit.
    ideal = money(min(walk * Decimal("0.86"), ask * Decimal("0.85"), walk - money(expected_profit * Decimal("0.15"))))
    if ideal < ZERO:
        ideal = ZERO
    acceptable = money(min(walk * Decimal("0.94"), (ideal + walk) / Decimal("2")))
    if acceptable < ideal:
        acceptable = ideal
    if acceptable > walk:
        acceptable = walk
    return Negotiation(
        ask,
        ideal,
        acceptable,
        walk,
        f"ASK €{ask} / IDEAL €{ideal} / GOOD BUY <= €{acceptable} / ABSOLUTE MAX €{walk}",
    )
