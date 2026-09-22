"""Parse owner-supplied JSON into a vehicle case. Missing fields stay unknown."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.domains.vehicles.auction_costs import AuctionFeeSchedule, PremiumBand
from app.domains.vehicles.cases import VehicleCase
from app.domains.vehicles.enums import (
    AuctionVatTreatment,
    BodyKind,
    CheckOutcome,
    Co2Basis,
    EvidencePosture,
    Fuel,
    ObservationStatus,
    RegistrationSignal,
)
from app.domains.vehicles.evidence import CheckResult
from app.domains.vehicles.history import HistoryInput, OdometerReading
from app.domains.vehicles.identity import ListingIdentity, VehicleIdentity, parse_listing_text
from app.domains.vehicles.market import MarketBook, MarketObservation
from app.domains.vehicles.provenance import HistoryPoint, KeeperEvidence, ProvenanceInput
from app.domains.vehicles.tax import Homologation


def _require_dt(value: str | None, label: str) -> datetime:
    parsed = _dt(value)
    if parsed is None:
        raise ValueError(f"{label} is required.")
    return parsed


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Timestamps must include a timezone.")
    return parsed


def _dec(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _posture(value: str | None) -> EvidencePosture:
    if not value:
        return EvidencePosture.UNKNOWN
    return EvidencePosture(value)


def _check(raw: dict | None, name: str) -> CheckResult | None:
    if not raw:
        return None
    return CheckResult(
        name=name,
        outcome=CheckOutcome(raw["outcome"]),
        posture=_posture(raw.get("posture")),
        source=str(raw.get("source") or ""),
        interpretation=str(raw.get("interpretation") or ""),
        blocking=bool(raw.get("blocking", False)),
        retrieved_at=_dt(raw.get("retrieved_at")),
        raw_reference=raw.get("raw_reference"),
    )


def _identity(raw: dict | None, title: str, description: str) -> VehicleIdentity:
    if not raw:
        return parse_listing_text(title, description)
    identity = parse_listing_text(title, description)
    for field_name in (
        "manufacturer",
        "model_family",
        "generation",
        "derivative",
        "wheelbase",
        "roof",
        "doors",
        "transmission",
        "registration",
        "vin",
        "colour",
        "eu_category",
    ):
        if raw.get(field_name):
            setattr(identity, field_name, raw[field_name])
    if raw.get("body"):
        identity.body = BodyKind(raw["body"])
    if raw.get("fuel"):
        identity.fuel = Fuel(raw["fuel"])
    if raw.get("year") is not None:
        identity.year = int(raw["year"])
    if raw.get("mileage_km") is not None:
        identity.mileage_km = int(raw["mileage_km"])
    if raw.get("seats") is not None:
        identity.seats = int(raw["seats"])
    if raw.get("power_ps") is not None:
        identity.power_ps = int(raw["power_ps"])
    if raw.get("mass_in_service_kg") is not None:
        identity.mass_in_service_kg = int(raw["mass_in_service_kg"])
    if raw.get("tpmlm_kg") is not None:
        identity.tpmlm_kg = int(raw["tpmlm_kg"])
    return identity


def _book(rows: list[dict] | None) -> MarketBook:
    book = MarketBook()
    for row in rows or []:
        book.append(
            MarketObservation(
                observation_id=str(row["observation_id"]),
                listing_id=str(row["listing_id"]),
                observed_at=_require_dt(row.get("observed_at"), "market observation observed_at"),
                manufacturer=str(row["manufacturer"]),
                model_family=str(row["model_family"]),
                year=None if row.get("year") is None else int(row["year"]),
                fuel=Fuel(row.get("fuel") or "UNKNOWN"),
                body=str(row.get("body") or "UNKNOWN"),
                wheelbase=row.get("wheelbase"),
                roof=row.get("roof"),
                transmission=row.get("transmission"),
                derivative=row.get("derivative"),
                mileage_km=None if row.get("mileage_km") is None else int(row["mileage_km"]),
                generation=row.get("generation"),
                asking_price_eur=_dec(row.get("asking_price_eur")),
                realised_price_eur=_dec(row.get("realised_price_eur")),
                seller_type=str(row.get("seller_type") or "unknown"),
                vat_presentation=str(row.get("vat_presentation") or "unknown"),
                location=str(row.get("location") or ""),
                status=ObservationStatus(row.get("status") or "ACTIVE"),
                source=str(row.get("source") or "owner"),
                url=row.get("url"),
            )
        )
    return book


def case_from_payload(data: dict) -> VehicleCase:
    if "as_of" not in data:
        raise ValueError("as_of is required.")
    as_of = _dt(str(data["as_of"]))
    if as_of is None:
        raise ValueError("as_of is required.")
    title = str(data.get("title") or "")
    description = str(data.get("description") or "")
    listing = ListingIdentity(
        source_id=str(data.get("source_id") or "cv_manual"),
        external_id=str(data.get("external_id") or "manual"),
        url=data.get("url"),
        title=title,
        seller=data.get("seller"),
        location=data.get("location"),
        currency=str(data.get("currency") or "EUR"),
        current_bid=_dec(data.get("current_bid")),
        hammer_basis=str(data.get("hammer_basis") or "UNKNOWN"),
        ends_at=_dt(data.get("ends_at")),
    )
    provenance_raw = data.get("provenance") or {}
    v5c_raw = provenance_raw.get("v5c")
    history_raw = provenance_raw.get("history") or []
    provenance = ProvenanceInput(
        registration_signal=RegistrationSignal(provenance_raw.get("registration_signal") or "UNKNOWN"),
        irish_registration_certificate=bool(provenance_raw.get("irish_registration_certificate")),
        irish_registration_reference=provenance_raw.get("irish_registration_reference"),
        v5c_original=None
        if not v5c_raw
        else KeeperEvidence(
            jurisdiction=str(v5c_raw["jurisdiction"]),
            resident_in=str(v5c_raw["resident_in"]),
            document=str(v5c_raw.get("document") or "V5C"),
            issued_at=_dt(v5c_raw.get("issued_at")),
        ),
        ni_import_declaration_reference=provenance_raw.get("ni_import_declaration_reference"),
        ni_import_declaration_vin=provenance_raw.get("ni_import_declaration_vin"),
        vehicle_vin=provenance_raw.get("vehicle_vin"),
        ni_service_references=tuple(provenance_raw.get("ni_service_references") or ()),
        history=tuple(
            HistoryPoint(
                jurisdiction=str(point["jurisdiction"]),
                observed_at=_dt(point["observed_at"]) or as_of,
                kind=str(point["kind"]),
                reference=str(point.get("reference") or ""),
            )
            for point in history_raw
        ),
        auction_country=provenance_raw.get("auction_country"),
    )
    history_block = data.get("history") or {}
    readings = tuple(
        OdometerReading(
            observed_at=_dt(row["observed_at"]) or as_of,
            mileage_km=int(row["mileage_km"]),
            source=str(row.get("source") or ""),
            reference=str(row.get("reference") or ""),
        )
        for row in history_block.get("readings") or []
    )
    history = HistoryInput(
        listing_mileage_km=None if history_block.get("listing_mileage_km") is None else int(history_block["listing_mileage_km"]),
        readings=readings,
        stolen=_check(history_block.get("stolen"), "stolen"),
        finance=_check(history_block.get("finance"), "finance"),
        write_off=_check(history_block.get("write_off"), "write_off"),
        declared_faults=tuple(history_block.get("declared_faults") or ()),
        keys=None if history_block.get("keys") is None else int(history_block["keys"]),
        service_history_reference=history_block.get("service_history_reference"),
    )
    homologation_raw = data.get("homologation")
    homologation = None
    if homologation_raw:
        homologation = Homologation(
            eu_category=str(homologation_raw["eu_category"]),
            seats=int(homologation_raw["seats"]),
            mass_in_service_kg=int(homologation_raw["mass_in_service_kg"]),
            tpmlm_kg=int(homologation_raw["tpmlm_kg"]),
            document=str(homologation_raw.get("document") or "CoC"),
            reference=str(homologation_raw.get("reference") or ""),
            separate_passenger_and_cargo_units=bool(homologation_raw.get("separate_passenger_and_cargo_units")),
        )
    schedule_raw = data.get("fee_schedule")
    schedule = None
    if schedule_raw:
        schedule = AuctionFeeSchedule(
            schedule_id=str(schedule_raw["schedule_id"]),
            source_id=str(schedule_raw["source_id"]),
            version=str(schedule_raw["version"]),
            effective_from=_dt(schedule_raw["effective_from"]) or as_of,
            retrieved_at=_dt(schedule_raw["retrieved_at"]) or as_of,
            evidence_url=str(schedule_raw.get("evidence_url") or ""),
            applies_to=str(schedule_raw.get("applies_to") or ""),
            bands=tuple(
                PremiumBand(up_to_eur=_dec(band.get("up_to_eur")), percent=Decimal(str(band["percent"])))
                for band in schedule_raw.get("bands") or []
            ),
            minimum_premium_eur=Decimal(str(schedule_raw.get("minimum_premium_eur") or "0")),
            premium_vat_rate=_dec(schedule_raw.get("premium_vat_rate")),
            documentation_fee_eur=Decimal(str(schedule_raw.get("documentation_fee_eur") or "0")),
            online_bidding_fee_eur=Decimal(str(schedule_raw.get("online_bidding_fee_eur") or "0")),
            collection_fee_eur=Decimal(str(schedule_raw.get("collection_fee_eur") or "0")),
        )
    vat_raw = data.get("vat_treatment")
    return VehicleCase(
        listing=listing,
        identity=_identity(data.get("identity"), title, description),
        as_of=as_of,
        provenance=provenance,
        history=history,
        book=_book(data.get("market_observations")),
        homologation=homologation,
        co2_g_per_km=_dec(data.get("co2_g_per_km")),
        co2_basis=Co2Basis(data.get("co2_basis") or "UNKNOWN"),
        nox_mg_per_km=_dec(data.get("nox_mg_per_km")),
        omsp_eur=_dec(data.get("omsp_eur")),
        omsp_source=data.get("omsp_source"),
        schedule=schedule,
        vat_treatment=AuctionVatTreatment(vat_raw) if vat_raw else AuctionVatTreatment.UNKNOWN,
        hammer_includes_vat=data.get("hammer_includes_vat"),
        owner_vat_registered=bool(data.get("owner_vat_registered")),
        commercial_vat_invoice_expected=bool(data.get("commercial_vat_invoice_expected")),
        transport_eur=_dec(data.get("transport_eur")),
        transport_posture=_posture(data.get("transport_posture")),
        border_transport_eur=_dec(data.get("border_transport_eur")),
        insurance_eur=_dec(data.get("insurance_eur")),
        payment_fee_eur=_dec(data.get("payment_fee_eur")),
        payment_fee_posture=_posture(data.get("payment_fee_posture")),
        duty_rate=_dec(data.get("duty_rate")),
        preferential_origin_proven=bool(data.get("preferential_origin_proven")),
        registration_fee_eur=_dec(data.get("registration_fee_eur")),
        registration_fee_posture=_posture(data.get("registration_fee_posture")),
        fx_eur_per_unit=_dec(data.get("fx_eur_per_unit")),
        fx_retrieved_at=_dt(data.get("fx_retrieved_at")),
        mechanical_inspected=bool(data.get("mechanical_inspected")),
        fuel_override=Fuel(data["fuel_override"]) if data.get("fuel_override") else None,
    )
