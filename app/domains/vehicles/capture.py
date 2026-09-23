"""Turn an owner-supplied Mid Ulster catalogue into normal vehicle cases."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.domains.vehicles.cases import VehicleCase
from app.domains.vehicles.evaluate import Evaluation, evaluate_vehicle
from app.domains.vehicles.history import HistoryInput
from app.domains.vehicles.identity import ListingIdentity, parse_listing_text, registration_signal
from app.domains.vehicles.ingest.mid_ulster import (
    PARSER_VERSION,
    SOURCE_ID,
    CatalogueParse,
    ParsedLot,
    fee_schedule_eur,
    parse_catalogue,
    vat_treatment,
)
from app.domains.vehicles.market import MarketBook
from app.domains.vehicles.provenance import ProvenanceInput


def catalogue_to_cases(
    text: str,
    book: MarketBook,
    *,
    as_of: datetime | None = None,
    fx_eur_per_gbp: Decimal | None = None,
    fx_retrieved_at: datetime | None = None,
) -> tuple[CatalogueParse, list[VehicleCase]]:
    parsed = parse_catalogue(text)
    moment = as_of or datetime.now(timezone.utc)
    schedule = fee_schedule_eur(parsed, fx_eur_per_gbp=fx_eur_per_gbp, retrieved_at=moment)
    cases: list[VehicleCase] = []
    skipped = 0
    for lot in parsed.lots:
        case = _case(lot, parsed, book, moment, schedule, fx_eur_per_gbp, fx_retrieved_at)
        if case is None:
            skipped += 1
            continue
        cases.append(case)
    parsed.skipped_not_vans = skipped
    return parsed, cases


def evaluate_cases(cases: list[VehicleCase]) -> list[Evaluation]:
    return [evaluate_vehicle(case) for case in cases]


def _case(
    lot: ParsedLot,
    parsed: CatalogueParse,
    book: MarketBook,
    as_of: datetime,
    schedule,
    fx: Decimal | None,
    fx_at: datetime | None,
) -> VehicleCase | None:
    identity = parse_listing_text(lot.title, " ".join(lot.raw_lines))
    if identity.model_family is None and "van" not in lot.title.lower():
        return None
    if lot.registration:
        identity.registration = lot.registration
        identity.registration_signal = registration_signal(lot.registration)
    if lot.year:
        identity.year = lot.year
    if lot.mileage_km:
        identity.mileage_km = lot.mileage_km
    if lot.fuel is not identity.fuel and lot.fuel.value != "UNKNOWN":
        identity.fuel = lot.fuel
    identity.identity_notes.append(f"parser:{PARSER_VERSION}")
    if lot.document_status:
        identity.identity_notes.append(f"document_status:{lot.document_status}")
    if lot.mot_expiry:
        identity.identity_notes.append(f"mot_or_psv_expiry:{lot.mot_expiry}")
    if lot.images:
        identity.identity_notes.append(f"images:{len(lot.images)}")
    external = f"{parsed.sale_code or 'sale'}-{lot.lot_number or lot.registration or lot.title[:24]}"
    treatment, inclusive = vat_treatment(lot)
    return VehicleCase(
        listing=ListingIdentity(
            source_id=SOURCE_ID,
            external_id=external.replace(" ", ""),
            url=lot.url,
            title=lot.title,
            seller=lot.vendor,
            location="Northern Ireland",
            currency="GBP",
            current_bid=lot.current_bid_gbp,
            ends_at=parsed.closes_at,
        ),
        identity=identity,
        as_of=as_of,
        provenance=ProvenanceInput(
            registration_signal=identity.registration_signal,
            vehicle_vin=identity.vin,
            auction_country="NI",
        ),
        history=HistoryInput(listing_mileage_km=lot.mileage_km),
        book=book,
        schedule=schedule,
        vat_treatment=treatment,
        hammer_includes_vat=inclusive,
        fx_eur_per_unit=fx,
        fx_retrieved_at=fx_at,
        auction_lot_vat_rate=Decimal("0.20") if treatment.value == "STANDARD_ON_HAMMER" else None,
    )
