"""Append-only Irish commercial-vehicle market observations.

A listing disappearing is not a sale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.domains.vehicles.enums import Fuel, ObservationStatus


@dataclass(frozen=True, slots=True)
class MarketObservation:
    observation_id: str
    listing_id: str
    observed_at: datetime
    manufacturer: str
    model_family: str
    year: int | None
    fuel: Fuel
    body: str
    wheelbase: str | None
    roof: str | None
    transmission: str | None
    derivative: str | None
    mileage_km: int | None
    generation: str | None
    asking_price_eur: Decimal | None
    realised_price_eur: Decimal | None
    seller_type: str
    vat_presentation: str
    location: str
    status: ObservationStatus
    source: str
    url: str | None = None
    confidence: Decimal = Decimal("0.5")
    registration: str | None = None
    engine: str | None = None
    listing_title: str | None = None
    condition_flags: tuple[str, ...] = ()
    native_price: Decimal | None = None
    native_currency: str | None = None
    parser_version: str | None = None
    raw_reference: str | None = None
    dealer_name: str | None = None
    advertised_price_eur: Decimal | None = None
    net_price_eur: Decimal | None = None
    gross_price_eur: Decimal | None = None
    vat_rate: Decimal | None = None
    vat_classification: str = "UNKNOWN"
    vat_fragment: str = ""
    vat_parser_version: str | None = None
    vat_confidence: Decimal = Decimal("0")
    source_updated_at: str | None = None


@dataclass(slots=True)
class MarketBook:
    observations: list[MarketObservation] = field(default_factory=list)

    def append(self, observation: MarketObservation) -> None:
        if any(existing.observation_id == observation.observation_id for existing in self.observations):
            raise ValueError(f"Observation {observation.observation_id} already exists and cannot be overwritten.")
        self.observations.append(observation)

    def as_of(self, moment: datetime) -> list[MarketObservation]:
        return [row for row in self.observations if row.observed_at <= moment]
