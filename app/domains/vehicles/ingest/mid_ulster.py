"""Mid Ulster Auctions catalogue parser.

The owner calls this house Dulster. The published name is Mid Ulster Auctions.
Unattended download of their site text is not implemented: their terms prohibit
copying website text without written consent. This module reads a catalogue the
owner pastes or uploads. It does not fetch midulsterauctions.com.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.domains.vehicles.auction_costs import AuctionFeeSchedule, PremiumBand
from app.domains.vehicles.enums import AuctionVatTreatment, Fuel

PARSER_VERSION = "mid-ulster-catalogue-1"
SOURCE_ID = "mid_ulster"
LONDON = ZoneInfo("Europe/London")

_FIELD = re.compile(
    r"^(Year|Serial/Reg#|Mileage/Clock|KMS/Miles/Hrs|Wrtd/Not Wrtd|Fuel Type|MOT/PSV|"
    r"Document Status|Vendor Disclosure|Vendor|VAT|VCAR|Buyers Premium|Lot|Current Bid|Starting Bid|Status)"
    r"\s*[:#]?\s*(.*)$",
    re.I,
)
_SALE = re.compile(r"\b(T\d{3,})\b", re.I)
_CLOSE = re.compile(
    r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})\s*(AM|PM)?",
    re.I,
)
_MONEY = re.compile(r"£?\s*([0-9][0-9,]*)")
_BAND = re.compile(
    r"£\s*([0-9][0-9,]*)\s*-\s*(?:£\s*([0-9][0-9,]*)|PLUS)\s*£\s*([0-9][0-9,]*)",
    re.I,
)
_URL = re.compile(r"https?://\S+")


@dataclass(slots=True)
class ParsedLot:
    lot_number: str | None
    title: str
    registration: str | None
    year: int | None
    mileage_km: int | None
    mileage_unit: str | None
    fuel: Fuel
    vat: str | None
    vendor: str | None
    vendor_disclosure: str | None
    vcar: str | None
    document_status: str | None
    mot_expiry: str | None
    current_bid_gbp: Decimal | None
    images: tuple[str, ...]
    url: str | None
    raw_lines: tuple[str, ...]


@dataclass(slots=True)
class CatalogueParse:
    parser_version: str
    sale_code: str | None
    closes_at: datetime | None
    premium_bands_gbp: tuple[tuple[Decimal | None, Decimal], ...]
    premium_vat_known: bool
    lots: list[ParsedLot] = field(default_factory=list)
    skipped_not_vans: int = 0


def parse_catalogue(text: str) -> CatalogueParse:
    lines = [line.strip() for line in text.splitlines()]
    sale = None
    for line in lines:
        match = _SALE.search(line)
        if match:
            sale = match.group(1).upper()
            break
    closes = _close_time("\n".join(lines))
    bands, vat_known = _premium(lines)
    lots = _lots(lines)
    return CatalogueParse(
        parser_version=PARSER_VERSION,
        sale_code=sale,
        closes_at=closes,
        premium_bands_gbp=bands,
        premium_vat_known=vat_known,
        lots=lots,
    )


def fee_schedule_eur(
    parsed: CatalogueParse,
    *,
    fx_eur_per_gbp: Decimal | None,
    retrieved_at: datetime,
) -> AuctionFeeSchedule | None:
    if fx_eur_per_gbp is None or fx_eur_per_gbp <= 0:
        return None
    if not parsed.premium_bands_gbp or not parsed.premium_vat_known:
        return None
    bands = tuple(
        PremiumBand(
            up_to_eur=None if up_to is None else (up_to * fx_eur_per_gbp).quantize(Decimal("0.01")),
            percent=Decimal("0"),
            fixed_eur=(fixed * fx_eur_per_gbp).quantize(Decimal("0.01")),
        )
        for up_to, fixed in parsed.premium_bands_gbp
    )
    return AuctionFeeSchedule(
        schedule_id=f"mid-ulster-{parsed.sale_code or 'catalogue'}",
        source_id=SOURCE_ID,
        version=PARSER_VERSION,
        effective_from=retrieved_at,
        retrieved_at=retrieved_at,
        evidence_url="owner-supplied-catalogue",
        applies_to="commercial_vehicles",
        bands=bands,
        minimum_premium_eur=Decimal("0"),
        premium_vat_rate=Decimal("0.20"),
        documentation_fee_eur=Decimal("0"),
        online_bidding_fee_eur=Decimal("0"),
        collection_fee_eur=Decimal("0"),
    )


def vat_treatment(lot: ParsedLot) -> tuple[AuctionVatTreatment, bool | None]:
    if lot.vat is None:
        return AuctionVatTreatment.UNKNOWN, None
    if lot.vat.upper() == "YES":
        return AuctionVatTreatment.STANDARD_ON_HAMMER, False
    if lot.vat.upper() == "NO":
        return AuctionVatTreatment.NO_VAT, False
    return AuctionVatTreatment.UNKNOWN, None


def _close_time(text: str) -> datetime | None:
    match = _CLOSE.search(text)
    if match is None:
        return None
    day, month, year, hour, minute, ampm = match.groups()
    hour_n = int(hour)
    if ampm:
        ampm = ampm.upper()
        if ampm == "PM" and hour_n < 12:
            hour_n += 12
        if ampm == "AM" and hour_n == 12:
            hour_n = 0
    return datetime(int(year), int(month), int(day), hour_n, int(minute), tzinfo=LONDON)


def _premium(lines: list[str]) -> tuple[tuple[tuple[Decimal | None, Decimal], ...], bool]:
    text = "\n".join(lines)
    if "buyers premium" not in text.lower():
        return (), False
    van_lines: list[str] = []
    capture = False
    for line in lines:
        folded = line.lower()
        if "cars, vans" in folded:
            capture = True
            continue
        if capture and ("council" in folded or "hgv" in folded or "all commission" in folded):
            break
        if capture and line:
            van_lines.append(line)
    bands: list[tuple[Decimal | None, Decimal]] = []
    for line in van_lines:
        match = _BAND.search(line)
        if not match:
            continue
        upper = match.group(2)
        fixed = Decimal(match.group(3).replace(",", ""))
        up_to = None if upper is None else Decimal(upper.replace(",", ""))
        bands.append((up_to, fixed))
    vat_known = "plus vat" in text.lower() or "plus VAT" in text
    return tuple(bands), vat_known


def _lots(lines: list[str]) -> list[ParsedLot]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if not line:
            continue
        if current and _looks_like_title(line) and _has_identity(current):
            blocks.append(current)
            current = [line]
            continue
        current.append(line)
    if current:
        blocks.append(current)
    lots: list[ParsedLot] = []
    for block in blocks:
        if not _has_identity(block):
            continue
        fields: dict[str, str] = {}
        images: list[str] = []
        title = ""
        seen_field = False
        for line in block:
            images.extend(_URL.findall(line))
            match = _FIELD.match(line)
            if match and match.group(2).strip():
                seen_field = True
                fields[match.group(1).lower()] = match.group(2).strip()
                continue
            if not seen_field and _looks_like_title(line):
                title = line
        if not title and not fields.get("serial/reg#"):
            continue
        lots.append(_lot(title, fields, tuple(images), tuple(block)))
    return lots


def _looks_like_title(line: str) -> bool:
    if _FIELD.match(line) or line.startswith("£") or line.lower().startswith("http"):
        return False
    if len(line) < 12:
        return False
    letters = sum(character.isalpha() for character in line)
    return letters >= 8 and line.upper() == line


def _has_identity(lines: list[str]) -> bool:
    for line in lines:
        match = _FIELD.match(line)
        if match and match.group(1).lower() in {"serial/reg#", "lot"} and match.group(2).strip():
            return True
    return False


def _lot(title: str, fields: dict[str, str], images: tuple[str, ...], raw: tuple[str, ...]) -> ParsedLot:
    unit = fields.get("kms/miles/hrs")
    mileage = _int(fields.get("mileage/clock"))
    mileage_km = None
    if mileage is not None:
        if unit and "mile" in unit.lower():
            mileage_km = int(Decimal(mileage) * Decimal("1.609344"))
        else:
            mileage_km = mileage
    year_text = fields.get("year") or ""
    year_match = re.search(r"(19|20)\d{2}", year_text)
    bid = _money(fields.get("current bid") or fields.get("starting bid"))
    url = images[0] if images else None
    return ParsedLot(
        lot_number=(fields.get("lot") or "").split()[0] or None,
        title=title,
        registration=_clean_reg(fields.get("serial/reg#")),
        year=int(year_match.group(0)) if year_match else None,
        mileage_km=mileage_km,
        mileage_unit=unit,
        fuel=_fuel(fields.get("fuel type")),
        vat=fields.get("vat"),
        vendor=fields.get("vendor"),
        vendor_disclosure=fields.get("vendor disclosure"),
        vcar=fields.get("vcar"),
        document_status=fields.get("document status"),
        mot_expiry=fields.get("mot/psv"),
        current_bid_gbp=bid,
        images=images,
        url=url,
        raw_lines=raw,
    )


def _fuel(value: str | None) -> Fuel:
    text = (value or "").lower()
    if "diesel" in text:
        return Fuel.DIESEL
    if "electric" in text or text == "ev":
        return Fuel.ELECTRIC
    if "hybrid" in text and "plug" in text:
        return Fuel.PHEV
    if "hybrid" in text:
        return Fuel.HYBRID
    if "petrol" in text:
        return Fuel.PETROL
    return Fuel.UNKNOWN


def _clean_reg(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().upper()
    return cleaned or None


def _int(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else None


def _money(value: str | None) -> Decimal | None:
    if not value:
        return None
    match = _MONEY.search(value)
    if match is None:
        return None
    return Decimal(match.group(1).replace(",", ""))
