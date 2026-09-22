"""Persistence for market observations. Duplicate ids are rejected."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.vehicles.market import MarketObservation
from app.domains.vehicles.orm import CvMarketObservationRow


def append_observation(session: Session, observation: MarketObservation) -> None:
    existing = session.get(CvMarketObservationRow, observation.observation_id)
    if existing is not None:
        raise ValueError(f"Observation {observation.observation_id} already exists and cannot be overwritten.")
    session.add(
        CvMarketObservationRow(
            observation_id=observation.observation_id,
            listing_id=observation.listing_id,
            model_family=observation.model_family,
            observed_at=observation.observed_at,
            source=observation.source,
            status=observation.status.value,
            payload={
                "manufacturer": observation.manufacturer,
                "year": observation.year,
                "fuel": observation.fuel.value,
                "body": observation.body,
                "asking_price_eur": str(observation.asking_price_eur) if observation.asking_price_eur is not None else None,
                "realised_price_eur": str(observation.realised_price_eur) if observation.realised_price_eur is not None else None,
                "seller_type": observation.seller_type,
                "vat_presentation": observation.vat_presentation,
                "location": observation.location,
                "url": observation.url,
            },
            note="append-only",
        )
    )


def list_family(session: Session, model_family: str) -> list[CvMarketObservationRow]:
    return list(
        session.query(CvMarketObservationRow)
        .filter(CvMarketObservationRow.model_family == model_family)
        .order_by(CvMarketObservationRow.observed_at)
        .all()
    )
