"""Longitudinal listing state. Disappearance is not a sale."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domains.vehicles.enums import ObservationStatus
from app.domains.vehicles.market import MarketObservation

_GONE = {
    ObservationStatus.DISAPPEARED,
    ObservationStatus.WITHDRAWN,
    ObservationStatus.EXPIRED,
}
_PRICE = {
    ObservationStatus.ACTIVE,
    ObservationStatus.PRICE_REDUCED,
    ObservationStatus.RELISTED,
    ObservationStatus.RETURNED,
    ObservationStatus.REALISED_SALE,
}


@dataclass(frozen=True, slots=True)
class ListingState:
    listing_id: str
    source: str
    first_seen: datetime
    last_seen: datetime
    status: str
    raw_status: str
    current_asking_eur: Decimal | None
    price_history_eur: tuple[str, ...]
    registration: str | None
    inferred_sale: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "listing_id": self.listing_id,
            "source": self.source,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "status": self.status,
            "raw_status": self.raw_status,
            "current_asking_eur": str(self.current_asking_eur) if self.current_asking_eur is not None else None,
            "price_history_eur": list(self.price_history_eur),
            "registration": self.registration,
            "inferred_sale": self.inferred_sale,
        }


def derive_listing_states(observations: list[MarketObservation]) -> list[ListingState]:
    grouped: dict[str, list[MarketObservation]] = {}
    for row in observations:
        grouped.setdefault(row.listing_id, []).append(row)
    states: list[ListingState] = []
    for listing_id, rows in grouped.items():
        ordered = sorted(rows, key=lambda item: item.observed_at)
        latest = ordered[-1]
        prices = tuple(
            str(row.asking_price_eur)
            for row in ordered
            if row.asking_price_eur is not None and row.status in _PRICE
        )
        status = _status(ordered)
        states.append(
            ListingState(
                listing_id=listing_id,
                source=latest.source,
                first_seen=ordered[0].observed_at,
                last_seen=latest.observed_at,
                status=status,
                raw_status=latest.status.value,
                current_asking_eur=latest.asking_price_eur if latest.status in _PRICE else None,
                price_history_eur=prices,
                registration=latest.registration,
                inferred_sale=False,
            )
        )
    return states


def _status(ordered: list[MarketObservation]) -> str:
    latest = ordered[-1]
    if latest.status is ObservationStatus.REALISED_SALE and latest.realised_price_eur is not None:
        return ObservationStatus.REALISED_SALE.value
    if latest.status in _GONE or latest.status is ObservationStatus.UNKNOWN:
        return ObservationStatus.DISAPPEARED.value if latest.status in _GONE else ObservationStatus.UNKNOWN.value
    previous_gone = any(row.status in _GONE for row in ordered[:-1])
    if previous_gone:
        return ObservationStatus.RETURNED.value
    prices = [row.asking_price_eur for row in ordered if row.asking_price_eur is not None]
    if len(prices) >= 2 and prices[-1] < prices[0]:
        return ObservationStatus.PRICE_REDUCED.value
    if latest.status is ObservationStatus.RELISTED:
        return ObservationStatus.RELISTED.value
    if latest.status in _PRICE:
        return ObservationStatus.ACTIVE.value
    return ObservationStatus.UNKNOWN.value


def status_for_new_observation(
    prior: list[MarketObservation],
    *,
    asking_price_eur: Decimal | None,
) -> ObservationStatus:
    if not prior:
        return ObservationStatus.ACTIVE
    ordered = sorted(prior, key=lambda item: item.observed_at)
    latest = ordered[-1]
    if latest.status in _GONE:
        return ObservationStatus.RETURNED
    if (
        asking_price_eur is not None
        and latest.asking_price_eur is not None
        and asking_price_eur < latest.asking_price_eur
    ):
        return ObservationStatus.PRICE_REDUCED
    return ObservationStatus.ACTIVE
