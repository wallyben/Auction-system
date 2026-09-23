"""Explicit commercial-van platform relationships.

Siblings can inform age and mileage effects. They are not price anchors.
usable_as_direct_comp stays false until a later calibration says otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

PLATFORM_MAP_VERSION = "cv-platforms-1"


@dataclass(frozen=True, slots=True)
class CommercialPlatformFamily:
    platform_id: str
    members: tuple[str, ...]
    generation_note: str
    usable_for_adjustment: bool = True
    usable_as_direct_comp: bool = False
    confidence: Decimal = Decimal("0.4")


PLATFORMS: tuple[CommercialPlatformFamily, ...] = (
    CommercialPlatformFamily(
        platform_id="small-psa-toyota",
        members=("berlingo", "partner", "combo", "proace_city"),
        generation_note="Shared small-van platform only where the generation actually matches. Not price-equivalent.",
    ),
    CommercialPlatformFamily(
        platform_id="medium-psa-toyota-stellantis",
        members=("dispatch", "expert", "proace", "vivaro"),
        generation_note="Medium Stellantis/Toyota vans. Vivaro generations are not all the same platform.",
    ),
    CommercialPlatformFamily(
        platform_id="trafic-primastar",
        members=("trafic", "primastar"),
        generation_note="Renault Trafic and Nissan Primastar/NV300 where the generation aligns.",
    ),
    CommercialPlatformFamily(
        platform_id="large-renault-nissan-stellantis",
        members=("master", "movano", "interstar"),
        generation_note="Large Renault group vans. Movano changed groups across generations.",
    ),
)

SMALL_VANS = frozenset(
    {"berlingo", "partner", "kangoo", "caddy", "combo", "citan", "doblo", "transit_connect", "proace_city", "nv200"}
)
MEDIUM_VANS = frozenset(
    {"transit_custom", "transporter", "vito", "trafic", "vivaro", "expert", "dispatch", "proace", "primastar"}
)
LARGE_VANS = frozenset(
    {"transit", "master", "movano", "interstar", "sprinter", "crafter", "boxer", "relay", "ducato"}
)


def platform_for(family: str) -> CommercialPlatformFamily | None:
    for group in PLATFORMS:
        if family in group.members:
            return group
    return None


def sibling_families(family: str) -> frozenset[str]:
    group = platform_for(family)
    if group is None or not group.usable_for_adjustment:
        return frozenset()
    return frozenset(member for member in group.members if member != family)


def size_class(family: str) -> str:
    if family in SMALL_VANS:
        return "small"
    if family in MEDIUM_VANS:
        return "medium"
    if family in LARGE_VANS:
        return "large"
    return "unknown"
