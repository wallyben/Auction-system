"""Canonical camera-body identities used for sold-comp queries.

Queries are built from structured identity, never generic "Sony camera".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.identity.schemas import StructuredIdentity

EBAY_CAMERA_CATEGORY_ID = "31388"

# CompSniper ebaySite values, UK first.
MARKETPLACE_SITES: tuple[tuple[str, str], ...] = (
    ("GB", "ebay.co.uk"),
    ("DE", "ebay.de"),
    ("FR", "ebay.fr"),
)

SITE_TO_TERRITORY = {
    "ebay.co.uk": "GB",
    "ebay.com": "US",
    "ebay.de": "DE",
    "ebay.fr": "FR",
    "ebay.it": "IT",
    "ebay.es": "ES",
    "ebay.ca": "CA",
    "ebay.com.au": "AU",
}

# Shared accessory/noise exclusions. Applied on every camera-body query.
_BODY_EXCLUSIONS = (
    "-cage",
    "-case",
    "-cover",
    "-battery",
    "-charger",
    "-manual",
    "-broken",
    '-"for parts"',
    "-kit",
    '-"screen protector"',
    "-silicone",
    "-smallrig",
    "-grip",
    "-strap",
    "-hood",
)


@dataclass(frozen=True, slots=True)
class CameraBody:
    canonical_id: str
    manufacturer: str
    family: str
    model: str
    generation: str
    mpn: str
    aliases: tuple[str, ...]
    extra_exclusions: tuple[str, ...]
    sanity_low_eur: int
    sanity_high_eur: int

    def structured(self) -> StructuredIdentity:
        return StructuredIdentity(
            product_class="camera_body",
            manufacturer=self.manufacturer,
            model=self.model,
            generation=self.generation,
            tier=self.family,
            body_or_kit="body",
            extra={"mpn": self.mpn, "canonical_id": self.canonical_id},
        )

    def keyword(self) -> str:
        """Exact-identity keyword plus eBay minus-sign exclusions."""
        primary = self.aliases[0]
        extras = " ".join(self.extra_exclusions + _BODY_EXCLUSIONS)
        return f"{primary} {extras}".strip()


CAMERA_BODIES: tuple[CameraBody, ...] = (
    CameraBody(
        "sony|a7-iii|body",
        "Sony",
        "A7",
        "A7 III",
        "III",
        "ILCE-7M3",
        ("Sony A7 III", "Sony Alpha 7 III", "ILCE-7M3", "A7III"),
        ("-A7IV", "-A7R", "-A7S", "-A7C", '-"A7 IV"', '-"A7 IIII"'),
        700,
        1600,
    ),
    CameraBody(
        "sony|a7-iv|body",
        "Sony",
        "A7",
        "A7 IV",
        "IV",
        "ILCE-7M4",
        ("Sony A7 IV", "Sony Alpha 7 IV", "ILCE-7M4", "A7IV"),
        ("-A7III", "-A7R", "-A7S", "-A7C", '-"A7 III"', '-"A7R IV"'),
        900,
        2000,
    ),
    CameraBody(
        "sony|a7r-iii|body",
        "Sony",
        "A7R",
        "A7R III",
        "III",
        "ILCE-7RM3",
        ("Sony A7R III", "Sony Alpha 7R III", "ILCE-7RM3", "A7RIII"),
        ("-A7RIV", "-A7S", "-A7C", '-"A7 IV"', '-"A7R IV"'),
        800,
        1800,
    ),
    CameraBody(
        "sony|a7r-iv|body",
        "Sony",
        "A7R",
        "A7R IV",
        "IV",
        "ILCE-7RM4",
        ("Sony A7R IV", "Sony Alpha 7R IV", "ILCE-7RM4", "A7RIV"),
        ("-A7RIII", "-A7S", "-A7C", '-"A7 IV"', '-"A7R V"'),
        1100,
        2400,
    ),
    CameraBody(
        "sony|a7s-iii|body",
        "Sony",
        "A7S",
        "A7S III",
        "III",
        "ILCE-7SM3",
        ("Sony A7S III", "Sony Alpha 7S III", "ILCE-7SM3", "A7SIII"),
        ("-A7IV", "-A7R", "-A7C", '-"A7 IV"'),
        1400,
        2800,
    ),
    CameraBody(
        "canon|r6|body",
        "Canon",
        "EOS R",
        "EOS R6",
        "I",
        "R6",
        ("Canon EOS R6", "Canon R6"),
        ("-R6II", '-"R6 II"', '-"R6 Mark II"', "-R5", "-R7", "-R8", "-R10"),
        800,
        1800,
    ),
    CameraBody(
        "canon|r6-ii|body",
        "Canon",
        "EOS R",
        "EOS R6 II",
        "II",
        "R6 II",
        ("Canon EOS R6 II", "Canon R6 Mark II", "Canon R6 II"),
        ("-R5", "-R7", "-R8", "-R10", '-"R6 Mark III"'),
        1100,
        2300,
    ),
    CameraBody(
        "canon|r5|body",
        "Canon",
        "EOS R",
        "EOS R5",
        "I",
        "R5",
        ("Canon EOS R5", "Canon R5"),
        ("-R5C", '-"R5 II"', "-R5II", "-R6", "-RP"),
        1400,
        2800,
    ),
    CameraBody(
        "nikon|z6-ii|body",
        "Nikon",
        "Z",
        "Z6 II",
        "II",
        "Z6II",
        ("Nikon Z6 II", "Nikon Z6II", "Z 6 II"),
        ("-Z7", "-Z8", "-Z9", "-Z5", '-"Z6 III"', "-Z6III"),
        800,
        1700,
    ),
    CameraBody(
        "nikon|z7-ii|body",
        "Nikon",
        "Z",
        "Z7 II",
        "II",
        "Z7II",
        ("Nikon Z7 II", "Nikon Z7II", "Z 7 II"),
        ("-Z6", "-Z8", "-Z9", "-Z5"),
        1000,
        2100,
    ),
    CameraBody(
        "fujifilm|x-t4|body",
        "Fujifilm",
        "X-T",
        "X-T4",
        "4",
        "X-T4",
        ("Fujifilm X-T4", "Fuji X-T4", "XT4"),
        ("-XT5", "-X-T5", "-X-T3", "-X-H"),
        700,
        1500,
    ),
    CameraBody(
        "fujifilm|x-t5|body",
        "Fujifilm",
        "X-T",
        "X-T5",
        "5",
        "X-T5",
        ("Fujifilm X-T5", "Fuji X-T5", "XT5"),
        ("-XT4", "-X-T4", "-X-T3", "-X-H"),
        900,
        1800,
    ),
)

_BY_ID = {body.canonical_id: body for body in CAMERA_BODIES}


def token_in(blob: str, needle: str) -> bool:
    """Alphanumeric-boundary match. Prevents GDDR6 matching Canon R6."""
    needle = (needle or "").strip().lower()
    blob = (blob or "").lower()
    if not needle:
        return False
    if re.search(r"[^a-z0-9]+", needle):
        return needle in blob
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", blob) is not None


def camera_by_id(canonical_id: str) -> CameraBody | None:
    return _BY_ID.get(canonical_id)


def camera_from_identity(
    *,
    brand: str | None,
    model: str | None,
    canonical_key: str | None = None,
    title: str = "",
) -> CameraBody | None:
    key = (canonical_key or "").lower()
    if key in _BY_ID:
        return _BY_ID[key]
    blob = f"{brand or ''} {model or ''} {title} {key}".lower()
    ranked = sorted(CAMERA_BODIES, key=lambda b: len(b.model), reverse=True)
    for body in ranked:
        needles = (body.canonical_id, body.model.lower(), body.mpn.lower(), *tuple(a.lower() for a in body.aliases))
        if any(token_in(blob, needle) for needle in needles):
            # Prefer more specific generation: A7 IV must not match A7 III first (sorted by model length).
            if body.generation == "III" and re.search(r"\b(iv|4)\b", blob) and "iii" not in blob and "7m3" not in blob:
                continue
            return body
    return None


def query_plan_for(body: CameraBody, *, marketplaces: tuple[str, ...] = ("GB", "DE", "FR")) -> list[dict[str, str]]:
    plan: list[dict[str, str]] = []
    site_by_territory = {territory: site for territory, site in MARKETPLACE_SITES}
    for territory in marketplaces:
        site = site_by_territory.get(territory.upper())
        if not site:
            continue
        plan.append(
            {
                "canonical_product_id": body.canonical_id,
                "variant": "body",
                "marketplace": territory.upper(),
                "ebay_site": site,
                "keyword": body.keyword(),
                "category_id": EBAY_CAMERA_CATEGORY_ID,
                "condition_bucket": "used",
            }
        )
    return plan
