"""Structured identity for the first commercial categories. Title similarity is not enough."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from app.models.enums import IdentityLevel

_STORAGE = re.compile(r"\b(64|128|256|512|1024|1|2)\s*(gb|tb)\b", re.I)
_RAM = re.compile(r"\b(8|16|18|24|32|36|48|64|96|128)\s*gb(?:\s*ram|\s*memory)?\b", re.I)
_CHIP = re.compile(r"\bm([1-4])(?:\s*(pro|max|ultra))?\b", re.I)
_SIZE = re.compile(r"\b(13|14|15|16)(?:\s*[- ]?\s*inch|\s*\")?\b", re.I)
_IPHONE = re.compile(
    r"\biphone\s*(\d{1,2}|x[sr]?)(?:\s*(pro(?:\s*max)?|plus|mini|air))?",
    re.I,
)
_A7 = re.compile(r"\ba7\s*(r|s|c)?\s*(iv|iii|ii|v|i)?\b|\bilce-7(r|s|c)?m?(\d)\b", re.I)
_CANON_R = re.compile(r"\b(?:canon\s+)?(?:eos\s+)?r(5|6)(?:\s*(c|ii|mark\s*ii))?\b", re.I)
_NIKON_Z = re.compile(r"\b(?:nikon\s+)?z\s*(6|7)\s*(ii|iii)?\b", re.I)
_FUJI_XT = re.compile(r"\b(?:fuji(?:film)?\s+)?x-?t([345])\b", re.I)
_GPU = re.compile(r"\b(rtx|gtx|rx)\s*(\d{3,4})\s*(ti|super|xt|xtx)?\b", re.I)
_UNLOCKED = re.compile(r"\b(unlocked|sim[- ]?free|ohne simlock)\b", re.I)


@dataclass(slots=True)
class StructuredIdentity:
    product_class: str
    manufacturer: str | None = None
    model: str | None = None
    generation: str | None = None
    tier: str | None = None
    storage: str | None = None
    ram: str | None = None
    chip: str | None = None
    size: str | None = None
    body_or_kit: str | None = None
    carrier: str | None = None
    extra: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    def canonical_parts(self) -> list[str]:
        return [
            part.lower()
            for part in [
                self.manufacturer,
                self.model,
                self.generation,
                self.tier,
                self.storage,
                self.ram,
                self.chip,
                self.size,
                self.body_or_kit,
                self.carrier,
            ]
            if part
        ]


def parse_phone(text: str) -> StructuredIdentity | None:
    match = _IPHONE.search(text or "")
    if not match:
        return None
    gen = match.group(1)
    tier = (match.group(2) or "base").lower().replace("  ", " ").strip()
    storage_m = _STORAGE.search(text or "")
    storage = storage_m.group(0).upper().replace(" ", "") if storage_m else None
    unlocked = bool(_UNLOCKED.search(text or ""))
    missing = []
    if not storage:
        missing.append("storage")
    return StructuredIdentity(
        product_class="primary",
        manufacturer="Apple",
        model=f"iPhone {gen} {tier}".strip(),
        generation=str(gen),
        tier=tier,
        storage=storage,
        carrier="unlocked" if unlocked else None,
        missing=missing,
    )


def parse_macbook(text: str) -> StructuredIdentity | None:
    blob = text or ""
    if "macbook" not in blob.lower():
        return None
    family = "air" if re.search(r"\bair\b", blob, re.I) else "pro" if re.search(r"\bpro\b", blob, re.I) else "macbook"
    size_m = _SIZE.search(blob)
    chip_m = _CHIP.search(blob)
    ram_m = _RAM.search(blob)
    storage_m = _STORAGE.search(blob)
    missing = []
    if not chip_m:
        missing.append("chip")
    if not storage_m:
        missing.append("storage")
    if not size_m:
        missing.append("size")
    chip = None
    if chip_m:
        chip = f"M{chip_m.group(1)}" + (f" {chip_m.group(2)}" if chip_m.group(2) else "")
        chip = chip.strip()
    return StructuredIdentity(
        product_class="primary",
        manufacturer="Apple",
        model=f"MacBook {family.title()}",
        generation=chip,
        tier=family,
        storage=storage_m.group(0).upper().replace(" ", "") if storage_m else None,
        ram=ram_m.group(0).upper().replace(" ", "") if ram_m else None,
        chip=chip,
        size=size_m.group(1) if size_m else None,
        missing=missing,
    )


def parse_camera(text: str) -> StructuredIdentity | None:
    blob = text or ""
    body = "kit" if re.search(r"\bkit\b", blob, re.I) else "body"
    if re.search(r"ilce-7m4|a7\s*iv|a7iv", blob, re.I) and not re.search(r"a7r|ilce-7rm|a7s|a7c", blob, re.I):
        return StructuredIdentity(
            product_class="camera_body",
            manufacturer="Sony",
            model="A7 IV",
            generation="IV",
            tier="A7",
            body_or_kit=body,
        )
    if re.search(r"ilce-7m3|a7\s*iii|a7iii", blob, re.I) and not re.search(r"a7\s*iv|a7r|a7s|a7c", blob, re.I):
        return StructuredIdentity(
            product_class="camera_body",
            manufacturer="Sony",
            model="A7 III",
            generation="III",
            tier="A7",
            body_or_kit=body,
        )
    if re.search(r"a7r\s*iv|a7riv|ilce-7rm4", blob, re.I):
        return StructuredIdentity(
            product_class="camera_body",
            manufacturer="Sony",
            model="A7R IV",
            generation="IV",
            tier="A7R",
            body_or_kit=body,
        )
    if re.search(r"a7r\s*iii|a7riii|ilce-7rm3", blob, re.I):
        return StructuredIdentity(
            product_class="camera_body",
            manufacturer="Sony",
            model="A7R III",
            generation="III",
            tier="A7R",
            body_or_kit=body,
        )
    if re.search(r"a7s\s*iii|a7siii|ilce-7sm3", blob, re.I):
        return StructuredIdentity(
            product_class="camera_body",
            manufacturer="Sony",
            model="A7S III",
            generation="III",
            tier="A7S",
            body_or_kit=body,
        )
    canon = _CANON_R.search(blob)
    if canon:
        num = canon.group(1)
        extra = (canon.group(2) or "").lower()
        if extra in {"ii", "mark ii"}:
            model, gen = f"EOS R{num} II", "II"
        elif extra == "c":
            model, gen = f"EOS R{num}C", "C"
        else:
            model, gen = f"EOS R{num}", "I"
        return StructuredIdentity(
            product_class="camera_body",
            manufacturer="Canon",
            model=model,
            generation=gen,
            tier="EOS R",
            body_or_kit=body,
        )
    nikon = _NIKON_Z.search(blob)
    if nikon:
        num = nikon.group(1)
        gen = (nikon.group(2) or "I").upper()
        return StructuredIdentity(
            product_class="camera_body",
            manufacturer="Nikon",
            model=f"Z{num} {gen}".strip(),
            generation=gen,
            tier="Z",
            body_or_kit=body,
        )
    fuji = _FUJI_XT.search(blob)
    if fuji:
        num = fuji.group(1)
        return StructuredIdentity(
            product_class="camera_body",
            manufacturer="Fujifilm",
            model=f"X-T{num}",
            generation=num,
            tier="X-T",
            body_or_kit=body,
        )
    if re.search(r"a7r|ilce-7rm", blob, re.I):
        gen = "IV" if re.search(r"iv|7rm4", blob, re.I) else "III" if re.search(r"iii|7rm3", blob, re.I) else None
        return StructuredIdentity(
            product_class="camera_body",
            manufacturer="Sony",
            model=f"A7R {gen or ''}".strip(),
            generation=gen,
            tier="A7R",
            body_or_kit=body,
        )
    match = _A7.search(blob)
    if not match:
        return None
    series = (match.group(1) or "").upper()
    gen = (match.group(2) or "").upper()
    model = f"A7{series} {gen}".strip()
    return StructuredIdentity(
        product_class="camera_body",
        manufacturer="Sony",
        model=model,
        generation=gen or None,
        tier=f"A7{series}" if series else "A7",
        body_or_kit=body,
    )


def parse_gpu(text: str) -> StructuredIdentity | None:
    blob = text or ""
    match = _GPU.search(blob)
    if not match:
        return None
    laptop = bool(re.search(r"\b(laptop|mobile|max-q|notebook)\b", blob, re.I))
    model = re.sub(r"\s+", " ", match.group(0)).upper()
    extra = {"form": "laptop" if laptop else "desktop"}
    return StructuredIdentity(
        product_class="primary",
        manufacturer="NVIDIA" if match.group(1).lower() in {"rtx", "gtx"} else "AMD",
        model=model,
        generation=match.group(2),
        tier=(match.group(3) or "").upper() or None,
        extra=extra,
        missing=["form_factor"] if laptop else [],
    )


def identity_level_from_structured(parsed: StructuredIdentity) -> tuple[IdentityLevel, Decimal]:
    if parsed.missing:
        return IdentityLevel.VARIANT, Decimal("0.80") if len(parsed.missing) == 1 else Decimal("0.62")
    if parsed.product_class != "primary":
        return IdentityLevel.CATEGORY, Decimal("0.30")
    return IdentityLevel.EXACT, Decimal("0.93")
