"""Canonical vehicle identity, separate from listing identity."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.domains.vehicles.catalogue import (
    MANUFACTURER_ALIASES,
    PARTS_TOKENS,
    PASSENGER_CAR_TOKENS,
    PASSENGER_NAME_TOKENS,
    VAN_FAMILIES,
    WMI_MANUFACTURER,
    VanFamily,
)
from app.domains.vehicles.enums import BodyKind, CommercialClass, Fuel, RegistrationSignal
from app.domains.vehicles.evidence import EvidenceLedger, EvidenceRecord
from app.domains.vehicles.enums import EvidencePosture

_YEAR = re.compile(r"\b(19[8-9]\d|20[0-2]\d)\b")
_VIN = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")
_POWER = re.compile(r"\b(\d{2,3})\s*(?:ps|bhp|hp)\b", re.I)
_IE_REG = re.compile(r"\b(\d{2,3}\s*-?\s*[A-Z]{1,2}\s*-?\s*\d{1,6})\b", re.I)
_GB_CURRENT = re.compile(r"\b([A-Z]{2}\s*\d{2}\s*[A-Z]{3})\b", re.I)
_NI_WEAK = re.compile(r"\b([A-Z]{3}\s*\d{1,4}|\d{1,4}\s*[A-Z]{3})\b", re.I)
_MILEAGE = re.compile(r"\b(\d{1,3}(?:[,\s]\d{3})+|\d{4,7})\s*(miles|mi|km|kilometres|kilometers)\b", re.I)

_PHRASES: tuple[tuple[str, VanFamily], ...] = tuple(
    sorted(
        ((phrase, family) for family in VAN_FAMILIES for phrase in family.phrases),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)


def _fold(text: str) -> str:
    normalised = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(char for char in normalised if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", ascii_text).strip().lower()


def normalise_registration(value: str | None) -> str | None:
    if not value:
        return None
    compact = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return compact or None


def registration_signal(value: str | None) -> RegistrationSignal:
    """Plate shape is a weak signal. It is not customs status."""

    if not value:
        return RegistrationSignal.UNKNOWN
    compact = normalise_registration(value) or ""
    if _GB_CURRENT.fullmatch(compact):
        return RegistrationSignal.GB_FORMAT
    if re.fullmatch(r"\d{2,3}[A-Z]{1,2}\d{1,6}", compact):
        return RegistrationSignal.IE_FORMAT
    if re.fullmatch(r"[A-Z]{3}\d{1,4}|\d{1,4}[A-Z]{3}", compact):
        return RegistrationSignal.NI_FORMAT_WEAK
    return RegistrationSignal.UNKNOWN


def _manufacturer(text: str) -> str | None:
    for aliases, canonical in MANUFACTURER_ALIASES:
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", text):
                return canonical
    return None


def _family(text: str) -> VanFamily | None:
    for phrase, family in _PHRASES:
        if re.search(rf"\b{re.escape(phrase)}\b", text):
            return family
    return None


def _fuel(text: str) -> Fuel:
    if re.search(r"\b(bev|electric|ev)\b", text) and not re.search(r"\b(hybrid|phev|plug-in)\b", text):
        return Fuel.ELECTRIC
    if re.search(r"\b(phev|plug-in)\b", text):
        return Fuel.PHEV
    if re.search(r"\bhybrid\b", text):
        return Fuel.HYBRID
    if re.search(r"\b(tdci|tdi|dci|cdti|crdi|diesel|hdi|bluetec|ecoblue)\b", text):
        return Fuel.DIESEL
    if re.search(r"\b(petrol|gasoline|tsi|tfsi)\b", text):
        return Fuel.PETROL
    return Fuel.UNKNOWN


def _body(text: str) -> BodyKind:
    if re.search(r"\b(tourneo|caravelle|multivan|california|minibus|mpv)\b", text):
        return BodyKind.MINIBUS
    if re.search(r"\b(crew\s*cab|crew\s*van|double\s*cab|6\s*seat|six\s*seat)\b", text):
        return BodyKind.CREW
    if re.search(r"\bkombi\b", text):
        return BodyKind.KOMBI
    if re.search(r"\b(window\s*van|glazed\s*van)\b", text):
        return BodyKind.WINDOW
    if re.search(r"\bluton\b", text):
        return BodyKind.LUTON
    if re.search(r"\btipper\b", text):
        return BodyKind.TIPPER
    if re.search(r"\b(dropside|drop\s*side)\b", text):
        return BodyKind.DROPSIDE
    if re.search(r"\b(chassis\s*cab|chassis-cab)\b", text):
        return BodyKind.CHASSIS
    if re.search(r"\b(panel\s*van|panelvan|van)\b", text):
        return BodyKind.PANEL
    return BodyKind.UNKNOWN


def _token(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.I)
    return match.group(1).lower() if match else None


def _mileage_km(text: str) -> int | None:
    match = _MILEAGE.search(text)
    if not match:
        return None
    number = int(re.sub(r"[^\d]", "", match.group(1)))
    unit = match.group(2).lower()
    if unit in {"miles", "mi"}:
        return int(Decimal(number) * Decimal("1.609344"))
    return number


def _seats(text: str) -> int | None:
    match = re.search(r"\b(\d)\s*[- ]?\s*seat", text)
    if match:
        return int(match.group(1))
    return None


def _is_parts(text: str) -> bool:
    return any(token in text for token in PARTS_TOKENS)


def _is_passenger_car(text: str, family: VanFamily | None) -> bool:
    if family is not None:
        return False
    return any(re.search(rf"\b{re.escape(token)}\b", text) for token in PASSENGER_CAR_TOKENS)


@dataclass(slots=True)
class VehicleIdentity:
    """What the vehicle is, independent of a single auction listing."""

    manufacturer: str | None = None
    model_family: str | None = None
    generation: str | None = None
    derivative: str | None = None
    body: BodyKind = BodyKind.UNKNOWN
    wheelbase: str | None = None
    roof: str | None = None
    doors: str | None = None
    fuel: Fuel = Fuel.UNKNOWN
    engine: str | None = None
    power_ps: int | None = None
    transmission: str | None = None
    year: int | None = None
    registration: str | None = None
    registration_signal: RegistrationSignal = RegistrationSignal.UNKNOWN
    vin: str | None = None
    colour: str | None = None
    seats: int | None = None
    eu_category: str | None = None
    mass_in_service_kg: int | None = None
    tpmlm_kg: int | None = None
    mileage_km: int | None = None
    commercial_class: CommercialClass = CommercialClass.UNKNOWN
    identity_notes: list[str] = field(default_factory=list)

    @property
    def vehicle_key(self) -> str | None:
        if self.vin:
            return f"vin:{self.vin}"
        registration = normalise_registration(self.registration)
        if registration:
            return f"reg:{registration}"
        return None


@dataclass(slots=True)
class ListingIdentity:
    source_id: str
    external_id: str
    url: str | None = None
    title: str = ""
    seller: str | None = None
    location: str | None = None
    currency: str = "EUR"
    current_bid: Decimal | None = None
    hammer_basis: str = "UNKNOWN"
    ends_at: datetime | None = None

    @property
    def listing_key(self) -> str:
        return f"{self.source_id}:{self.external_id}"


def parse_listing_text(title: str, description: str = "") -> VehicleIdentity:
    """Parse a listing. Structured documents must override these guesses later."""

    text = _fold(f"{title} {description}")
    identity = VehicleIdentity()
    family = _family(text)
    manufacturer = _manufacturer(text)
    if family is not None:
        identity.model_family = family.family
        identity.manufacturer = manufacturer or family.manufacturer
        if manufacturer and manufacturer != family.manufacturer and family.manufacturer not in {manufacturer, "vauxhall", "opel"}:
            # Opel and Vauxhall share families. Other clashes are noted.
            if not (
                {manufacturer, family.manufacturer} <= {"vauxhall", "opel"}
                or family.manufacturer in {"vauxhall", "opel"}
                and manufacturer in {"vauxhall", "opel"}
            ):
                identity.identity_notes.append(
                    f"Title manufacturer {manufacturer} does not match family {family.manufacturer}."
                )
                identity.manufacturer = manufacturer
    else:
        identity.manufacturer = manufacturer

    if any(token in text for token in PASSENGER_NAME_TOKENS):
        identity.body = BodyKind.MINIBUS
        identity.commercial_class = CommercialClass.PASSENGER
        identity.identity_notes.append("People-mover name. Not treated as an N1 panel van.")
    elif _is_parts(text):
        identity.commercial_class = CommercialClass.PARTS_OR_NOT_A_VEHICLE
        identity.identity_notes.append("Listing describes parts or a breaker, not a whole vehicle.")
    elif _is_passenger_car(text, family):
        identity.commercial_class = CommercialClass.PASSENGER
        identity.identity_notes.append("Passenger-car name. Outside the commercial-van universe.")
    else:
        identity.body = _body(text)

    identity.fuel = _fuel(text)
    year = _YEAR.search(text)
    identity.year = int(year.group(1)) if year else None
    power = _POWER.search(text)
    identity.power_ps = int(power.group(1)) if power else None
    identity.wheelbase = _token(text, r"\b(swb|lwb|mwb|l1|l2|l3|l4)\b")
    identity.roof = _token(text, r"\b(h1|h2|h3)\b")
    if re.search(r"\b(automatic|dsg|auto)\b", text):
        identity.transmission = "automatic"
    elif re.search(r"\bmanual\b", text):
        identity.transmission = "manual"
    identity.mileage_km = _mileage_km(text)
    identity.seats = _seats(text)
    vin = _VIN.search(title.upper() + " " + description.upper())
    identity.vin = vin.group(1) if vin else None
    reg = _IE_REG.search(title) or _GB_CURRENT.search(title) or _NI_WEAK.search(title)
    if reg:
        identity.registration = normalise_registration(reg.group(1))
        identity.registration_signal = registration_signal(identity.registration)
    if identity.commercial_class is CommercialClass.UNKNOWN:
        identity.commercial_class = _commercial_class(identity)
    return identity


def _commercial_class(identity: VehicleIdentity) -> CommercialClass:
    goods_bodies = {BodyKind.PANEL, BodyKind.CHASSIS, BodyKind.TIPPER, BodyKind.DROPSIDE, BodyKind.LUTON}
    if identity.body in {BodyKind.CREW, BodyKind.KOMBI, BodyKind.MINIBUS, BodyKind.WINDOW}:
        return CommercialClass.CREW_OR_MULTI_SEAT
    if identity.seats is not None and identity.seats >= 4:
        return CommercialClass.CREW_OR_MULTI_SEAT
    if identity.model_family and identity.body in goods_bodies:
        return CommercialClass.N1_GOODS
    if identity.model_family and identity.body is BodyKind.UNKNOWN and (identity.seats is None or identity.seats < 4):
        # A van family without a body word is not proof of N1.
        return CommercialClass.UNKNOWN
    return CommercialClass.UNKNOWN


def apply_vin_consistency(identity: VehicleIdentity, ledger: EvidenceLedger) -> None:
    if not identity.vin:
        ledger.add(
            EvidenceRecord(
                field="vin",
                posture=EvidencePosture.UNKNOWN,
                status="ABSENT",
                confidence=Decimal("0"),
                source="listing",
                interpretation="No VIN in the listing. Identity cannot be tied to a chassis.",
                blocking=True,
            )
        )
        return
    wmi = identity.vin[:3]
    hinted = WMI_MANUFACTURER.get(wmi)
    if hinted and identity.manufacturer and hinted != identity.manufacturer:
        if not ({hinted, identity.manufacturer} <= {"opel", "vauxhall"}):
            ledger.add(
                EvidenceRecord(
                    field="vin",
                    posture=EvidencePosture.PROVEN,
                    status="MANUFACTURER_CONFLICT",
                    confidence=Decimal("0.9"),
                    source="iso3779-wmi-hint",
                    interpretation=f"VIN WMI {wmi} points at {hinted}, not {identity.manufacturer}.",
                    blocking=True,
                )
            )
            return
    ledger.add(
        EvidenceRecord(
            field="vin",
            posture=EvidencePosture.ESTIMATED,
            status="PRESENT_UNVERIFIED",
            confidence=Decimal("0.4"),
            source="listing",
            interpretation="A 17-character VIN was parsed. It has not been checked against a register.",
            blocking=False,
        )
    )


@dataclass(frozen=True, slots=True)
class Appearance:
    vehicle_key: str
    listing_key: str
    source_id: str
    external_id: str


def detect_reappearances(appearances: list[Appearance]) -> list[dict[str, object]]:
    """Same vehicle key on more than one listing is a reappearance, not a new asset."""

    grouped: dict[str, list[Appearance]] = {}
    for appearance in appearances:
        grouped.setdefault(appearance.vehicle_key, []).append(appearance)
    found: list[dict[str, object]] = []
    for vehicle_key, rows in grouped.items():
        listing_keys = {row.listing_key for row in rows}
        if len(listing_keys) > 1:
            found.append(
                {
                    "vehicle_key": vehicle_key,
                    "listing_keys": sorted(listing_keys),
                    "count": len(listing_keys),
                }
            )
    return found
