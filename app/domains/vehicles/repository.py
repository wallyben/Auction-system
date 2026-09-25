"""Persistence for market observations. Duplicate ids are rejected."""

from __future__ import annotations

from decimal import Decimal

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
            payload=_payload(observation),
            note="append-only",
        )
    )


def list_observations(session: Session, *, limit: int = 5000) -> list[CvMarketObservationRow]:
    return list(
        session.query(CvMarketObservationRow).order_by(CvMarketObservationRow.observed_at.desc()).limit(limit).all()
    )


def observation_from_row(row: CvMarketObservationRow) -> MarketObservation:
    from app.domains.vehicles.enums import Fuel, ObservationStatus

    payload = row.payload or {}
    fuel_name = str(payload.get("fuel") or "UNKNOWN")
    try:
        fuel = Fuel(fuel_name)
    except ValueError:
        fuel = Fuel.UNKNOWN
    try:
        status = ObservationStatus(row.status)
    except ValueError:
        status = ObservationStatus.UNKNOWN
    return MarketObservation(
        observation_id=row.observation_id,
        listing_id=row.listing_id,
        observed_at=row.observed_at,
        manufacturer=str(payload.get("manufacturer") or ""),
        model_family=row.model_family,
        year=payload.get("year"),
        fuel=fuel,
        body=str(payload.get("body") or "UNKNOWN"),
        wheelbase=payload.get("wheelbase"),
        roof=payload.get("roof"),
        transmission=payload.get("transmission"),
        derivative=payload.get("derivative"),
        mileage_km=payload.get("mileage_km"),
        generation=payload.get("generation"),
        asking_price_eur=_money(payload.get("asking_price_eur")),
        realised_price_eur=_money(payload.get("realised_price_eur")),
        seller_type=str(payload.get("seller_type") or ""),
        vat_presentation=str(payload.get("vat_presentation") or "unknown"),
        location=str(payload.get("location") or ""),
        status=status,
        source=row.source,
        url=payload.get("url"),
        registration=payload.get("registration"),
        engine=payload.get("engine"),
        listing_title=payload.get("listing_title"),
        parser_version=payload.get("parser_version"),
        raw_reference=payload.get("raw_reference"),
        dealer_name=payload.get("dealer_name"),
        advertised_price_eur=_money(payload.get("advertised_price_eur")),
        net_price_eur=_money(payload.get("net_price_eur")),
        gross_price_eur=_money(payload.get("gross_price_eur")),
        vat_rate=_money(payload.get("vat_rate")),
        vat_classification=str(payload.get("vat_classification") or "UNKNOWN"),
        vat_fragment=str(payload.get("vat_fragment") or ""),
        vat_parser_version=payload.get("vat_parser_version"),
        vat_confidence=_money(payload.get("vat_confidence")) or Decimal("0"),
        source_updated_at=payload.get("source_updated_at"),
        source_type=str(payload.get("source_type") or ""),
        capture_method=str(payload.get("capture_method") or ""),
        evidence_quality=str(payload.get("evidence_quality") or ""),
        geography=str(payload.get("geography") or "UNKNOWN"),
        price_status=str(payload.get("price_status") or ""),
        cross_source_duplicate_group_id=payload.get("cross_source_duplicate_group_id"),
        mileage_evidence=str(payload.get("mileage_evidence") or ""),
        price_evidence=str(payload.get("price_evidence") or ""),
        listing_class=str(payload.get("listing_class") or ""),
        source_observed_at=_when(payload.get("source_observed_at")),
    )


def _payload(observation: MarketObservation) -> dict[str, object]:
    return {
        "manufacturer": observation.manufacturer,
        "year": observation.year,
        "fuel": observation.fuel.value,
        "body": observation.body,
        "wheelbase": observation.wheelbase,
        "roof": observation.roof,
        "transmission": observation.transmission,
        "derivative": observation.derivative,
        "mileage_km": observation.mileage_km,
        "generation": observation.generation,
        "asking_price_eur": _text(observation.asking_price_eur),
        "realised_price_eur": _text(observation.realised_price_eur),
        "seller_type": observation.seller_type,
        "vat_presentation": observation.vat_presentation,
        "location": observation.location,
        "url": observation.url,
        "registration": observation.registration,
        "engine": observation.engine,
        "listing_title": observation.listing_title,
        "parser_version": observation.parser_version,
        "raw_reference": observation.raw_reference,
        "dealer_name": observation.dealer_name,
        "advertised_price_eur": _text(observation.advertised_price_eur),
        "net_price_eur": _text(observation.net_price_eur),
        "gross_price_eur": _text(observation.gross_price_eur),
        "vat_rate": _text(observation.vat_rate),
        "vat_classification": observation.vat_classification,
        "vat_fragment": observation.vat_fragment,
        "vat_parser_version": observation.vat_parser_version,
        "vat_confidence": _text(observation.vat_confidence),
        "source_updated_at": observation.source_updated_at,
        "source_type": observation.source_type,
        "capture_method": observation.capture_method,
        "evidence_quality": observation.evidence_quality,
        "geography": observation.geography,
        "price_status": observation.price_status,
        "cross_source_duplicate_group_id": observation.cross_source_duplicate_group_id,
        "mileage_evidence": observation.mileage_evidence,
        "price_evidence": observation.price_evidence,
        "listing_class": observation.listing_class,
        "source_observed_at": observation.source_observed_at.isoformat() if observation.source_observed_at else None,
        "model_version": "arie-native-v1",
    }


def _text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _when(value: object) -> datetime | None:
    if not value:
        return None
    from datetime import datetime

    parsed = datetime.fromisoformat(str(value))
    return parsed


def _money(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def list_family(session: Session, model_family: str) -> list[CvMarketObservationRow]:
    return list(
        session.query(CvMarketObservationRow)
        .filter(CvMarketObservationRow.model_family == model_family)
        .order_by(CvMarketObservationRow.observed_at)
        .all()
    )
