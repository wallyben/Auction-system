"""Read the frozen T426 pre-bid snapshot. The file is not an auction download."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from app.domains.vehicles.enums import BodyKind, Fuel
from app.domains.vehicles.ingest.mid_ulster import CatalogueParse, ParsedLot

_ROW = re.compile(r"^(\d+)\s*\|\s*([A-Z0-9_]+)\s*\|\s*(.+)$")
_BAND = re.compile(r"GBP\s*(\d+)\s*-\s*(\d+)\s*:\s*GBP\s*(\d+)", re.I)
_FX = re.compile(r"^GBP_EUR:\s*([0-9.]+)")


def parse_t426_snapshot(text: str) -> tuple[CatalogueParse, Decimal | None]:
    fx = None
    bands: list[tuple[Decimal | None, Decimal]] = []
    lots: list[ParsedLot] = []
    for raw in text.splitlines():
        line = raw.strip()
        fx_match = _FX.match(line)
        if fx_match:
            fx = Decimal(fx_match.group(1))
        band = _BAND.search(line)
        if band and "HGV" not in line.upper():
            bands.append((Decimal(band.group(2)), Decimal(band.group(3))))
        row = _ROW.match(line)
        if row is None or " | " not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 12 or not parts[0].isdigit():
            continue
        lots.append(_lot(parts))
    if bands:
        bands[-1] = (None, bands[-1][1])
    parsed = CatalogueParse(
        parser_version="t426-snapshot-1",
        sale_code="T426",
        closes_at=None,
        premium_bands_gbp=tuple(bands),
        premium_vat_known=True,
        lots=lots,
    )
    return parsed, fx


def _lot(parts: list[str]) -> ParsedLot:
    lot_number, hint, title, first_reg, reg, mileage, unit, fuel, _mot, documents, vat, vendor, *rest = parts
    vcar = rest[-1] if rest else ""
    year = int(first_reg[:4]) if len(first_reg) >= 4 and first_reg[:4].isdigit() else None
    miles = int(mileage.replace(",", "")) if mileage.isdigit() or mileage.replace(",", "").isdigit() else None
    km = miles
    if miles is not None and unit.lower().startswith("mi"):
        km = int(Decimal(miles) * Decimal("1.609344"))
    return ParsedLot(
        lot_number=lot_number,
        title=title,
        registration=reg or None,
        year=year,
        mileage_km=km,
        mileage_unit=unit or None,
        fuel=_fuel(fuel),
        vat=vat or None,
        vendor=vendor or None,
        vendor_disclosure=hint,
        vcar=vcar or None,
        document_status=documents or None,
        mot_expiry=_mot if _mot and _mot.lower() != "unknown" else None,
        current_bid_gbp=None,
        images=(),
        url=None,
        raw_lines=(hint, title, vcar or ""),
    )


def body_for_hint(hint: str, title: str) -> BodyKind:
    name = hint.upper()
    folded = title.lower()
    if "NON_RUNNER" in name or "non-runner" in folded:
        return BodyKind.UNKNOWN
    if name == "TIPPER" or "tipper" in folded:
        return BodyKind.TIPPER
    if name == "CREW_VAN" or "crew" in folded:
        return BodyKind.CREW
    if "DROPSIDE" in name or "dropside" in folded:
        return BodyKind.DROPSIDE
    if "PICKUP" in name or "pickup" in folded or "fridge" in folded:
        return BodyKind.UNKNOWN
    if name == "VAN":
        return BodyKind.PANEL
    return BodyKind.UNKNOWN


def _fuel(value: str) -> Fuel:
    try:
        return Fuel(value.strip().upper())
    except ValueError:
        return Fuel.UNKNOWN
