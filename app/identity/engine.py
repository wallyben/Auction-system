"""Product identity resolution from listing text and identifiers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from app.models.enums import IdentityLevel

BRANDS = (
    "apple", "samsung", "sony", "canon", "nikon", "fujifilm", "leica", "panasonic",
    "olympus", "om system", "dji", "gopro", "microsoft", "dell", "hp", "lenovo",
    "asus", "acer", "lg", "bosch", "dewalt", "makita", "milwaukee", "festool",
    "nintendo", "playstation", "xbox", "steam deck", "valve", "bose", "sennheiser",
    "shure", "audio-technica", "pioneer", "technics", "allen & heath", "denon",
    "yamaha", "fender", "gibson", "prs", "roland", "korg", "moog", "teenage engineering",
    "dyson", "miele", "kitchenaid", "breville", "garmin", "apple watch", "google",
    "meta", "oculus", "insta360", "sigma", "tamron", "godox", "profoto", "wacom",
    "ipad", "iphone", "macbook", "airpods", "surface", "thinkpad", "blackmagic",
    "atomos", "red digital", "arri", "zoom", "rode", "lego", "cricut", "prusa",
)

STORAGE_RE = re.compile(r"\b(\d+)\s?(gb|tb)\b", re.I)
GTIN_RE = re.compile(r"\b(\d{8}|\d{12}|\d{13}|\d{14})\b")
MODEL_RE = re.compile(
    r"\b("
    r"a7(?:r|s)?(?:\s?iv|\s?iii|\s?ii)?|"
    r"iphone\s?\d{1,2}(?:\s?(?:pro(?:\s?max)?|plus|mini))?|"
    r"macbook(?:\s?air|\s?pro)?|"
    r"ipad(?:\s?pro|\s?air|\s?mini)?|"
    r"rf\s?\d{2,3}(?:-\d{2,3})?|"
    r"ef\s?\d{2,3}|"
    r"switch(?:\s?oled|\s?lite)?|"
    r"ps5|xbox\s?series\s?[xs]|"
    r"cdj[-\s]?\d{3,4}|"
    r"dji\s?(?:mini|air|mavic|rs)\s?\d?"
    r")\b",
    re.I,
)
LOT_RE = re.compile(
    r"\b(job\s?lot|lot\s+of\s+\d+|bundle|mixed\s+lot|\d+\s*x\s+|wholesale\s+lot)\b",
    re.I,
)


@dataclass(slots=True)
class IdentityEvidence:
    kind: str
    value: str
    weight: Decimal


@dataclass(slots=True)
class ProductIdentity:
    brand: str | None
    family: str | None
    model: str | None
    variant: str | None
    gtin: str | None
    mpn: str | None
    category: str | None
    storage: str | None
    identifiers: dict[str, str]
    included: list[str]
    missing: list[str]
    level: IdentityLevel
    confidence: Decimal
    evidence: list[IdentityEvidence] = field(default_factory=list)
    is_lot: bool = False
    canonical_key: str = ""
    product_class: str = "primary"
    attributes: dict[str, str] = field(default_factory=dict)
    compatible_camera_ids: tuple[str, ...] = ()


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _find_brand(text: str) -> tuple[str | None, Decimal]:
    for brand in sorted(BRANDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(brand)}\b", text, re.I):
            return brand.title() if brand != "dji" else "DJI", Decimal("0.35")
    return None, Decimal("0")


def identify_listing(
    *,
    title: str,
    description: str = "",
    brand_hint: str | None = None,
    model_hint: str | None = None,
    gtin: str | None = None,
    mpn: str | None = None,
    category: str | None = None,
) -> ProductIdentity:
    """Resolve the strongest honest identity from available listing fields."""
    blob = f"{title}\n{description}\n{brand_hint or ''}\n{model_hint or ''}"
    text = _norm(blob)
    evidence: list[IdentityEvidence] = []
    confidence = Decimal("0")

    brand, brand_w = _find_brand(text)
    if brand_hint:
        brand = brand_hint.strip().title()
        brand_w = Decimal("0.45")
        evidence.append(IdentityEvidence("source_brand", brand, brand_w))
    elif brand:
        evidence.append(IdentityEvidence("title_brand", brand, brand_w))
    confidence += brand_w

    model = None
    if model_hint:
        model = model_hint.strip()
        confidence += Decimal("0.35")
        evidence.append(IdentityEvidence("source_model", model, Decimal("0.35")))
    else:
        match = MODEL_RE.search(text)
        if match:
            model = re.sub(r"\s+", " ", match.group(1)).strip()
            confidence += Decimal("0.25")
            evidence.append(IdentityEvidence("title_model", model, Decimal("0.25")))

    storage = None
    storage_match = STORAGE_RE.search(text)
    if storage_match:
        storage = storage_match.group(0).upper().replace(" ", "")
        evidence.append(IdentityEvidence("storage", storage, Decimal("0.08")))
        confidence += Decimal("0.08")

    found_gtin = gtin or (GTIN_RE.search(title) or GTIN_RE.search(description) or [None, None])[0]
    if isinstance(found_gtin, re.Match):
        found_gtin = found_gtin.group(1)
    if found_gtin:
        confidence += Decimal("0.30")
        evidence.append(IdentityEvidence("gtin", str(found_gtin), Decimal("0.30")))

    is_lot = bool(LOT_RE.search(text))
    if is_lot:
        confidence = min(confidence, Decimal("0.55"))
        evidence.append(IdentityEvidence("lot_flag", "true", Decimal("0")))

    if found_gtin and (brand or model):
        level = IdentityLevel.EXACT
    elif brand and model:
        level = IdentityLevel.VARIANT if storage else IdentityLevel.EXACT
        if not storage:
            level = IdentityLevel.FAMILY if not model_hint else IdentityLevel.EXACT
            if MODEL_RE.search(text):
                level = IdentityLevel.EXACT
    elif brand:
        level = IdentityLevel.FAMILY
        confidence = min(confidence, Decimal("0.45"))
    elif category:
        level = IdentityLevel.CATEGORY
        confidence = min(confidence, Decimal("0.25"))
    else:
        level = IdentityLevel.UNKNOWN
        confidence = min(confidence, Decimal("0.15"))

    if confidence > Decimal("0.99"):
        confidence = Decimal("0.99")

    key_parts = [brand or "unk", model or "unk", storage or "", found_gtin or "", category or ""]
    canonical_key = "|".join(part.lower() for part in key_parts if part)

    return ProductIdentity(
        brand=brand,
        family=brand,
        model=model,
        variant=storage,
        gtin=str(found_gtin) if found_gtin else None,
        mpn=mpn,
        category=category,
        storage=storage,
        identifiers={k: v for k, v in {"gtin": found_gtin, "mpn": mpn}.items() if v},
        included=[],
        missing=[],
        level=level,
        confidence=confidence,
        evidence=evidence,
        is_lot=is_lot,
        canonical_key=canonical_key or _norm(title)[:180],
    )


identify_listing = identify_listing  # canonical

identify_listing = identify_listing
