"""Auction/listing urgency. Never recommend irrational early bidding."""

from __future__ import annotations

from app.models.enums import Urgency


def classify_urgency(*, listing_type: str, ends_in_hours: float | None, money_ready: bool) -> Urgency:
    if not money_ready:
        return Urgency.IGNORE if listing_type == "auction" and ends_in_hours is not None and ends_in_hours < 1 else Urgency.WATCH
    if listing_type != "auction":
        return Urgency.ACT_NOW if money_ready else Urgency.WATCH
    if ends_in_hours is None:
        return Urgency.WATCH
    if ends_in_hours > 24:
        return Urgency.BID_LATER
    if ends_in_hours > 2:
        return Urgency.WATCH
    return Urgency.ACT_NOW
