"""Discovery universe for common Irish commercial vans.

This is not a VRT whitelist. A family match never proves €200 VRT,
N1 type-approval, or Irish resale value.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VanFamily:
    manufacturer: str
    family: str
    phrases: tuple[str, ...]


def _family(manufacturer: str, family: str, *phrases: str) -> VanFamily:
    return VanFamily(manufacturer=manufacturer, family=family, phrases=phrases)


# Longer phrases are matched before shorter ones. "Transit Custom" must win
# over "Transit". Sibling platforms are separate families on purpose.
VAN_FAMILIES: tuple[VanFamily, ...] = (
    _family("citroen", "berlingo", "berlingo"),
    _family("peugeot", "partner", "partner"),
    _family("renault", "kangoo", "kangoo"),
    _family("volkswagen", "caddy", "caddy"),
    _family("ford", "transit_connect", "transit connect", "transit-connect"),
    _family("vauxhall", "combo", "combo"),
    _family("opel", "combo", "combo"),
    _family("fiat", "doblo", "doblo", "doblò"),
    _family("mercedes-benz", "citan", "citan"),
    _family("nissan", "nv200", "nv200", "nv 200"),
    _family("toyota", "proace_city", "proace city"),
    _family("peugeot", "expert", "expert"),
    _family("citroen", "dispatch", "dispatch"),
    _family("toyota", "proace", "proace"),
    _family("vauxhall", "vivaro", "vivaro"),
    _family("opel", "vivaro", "vivaro"),
    _family("renault", "trafic", "trafic"),
    _family("nissan", "primastar", "primastar", "nv300", "nv 300"),
    _family("ford", "transit_custom", "transit custom"),
    _family("volkswagen", "transporter", "transporter"),
    _family("mercedes-benz", "vito", "vito"),
    _family("ford", "transit", "transit"),
    _family("renault", "master", "master"),
    _family("vauxhall", "movano", "movano"),
    _family("opel", "movano", "movano"),
    _family("nissan", "interstar", "interstar", "nv400", "nv 400"),
    _family("peugeot", "boxer", "boxer"),
    _family("citroen", "relay", "relay"),
    _family("fiat", "ducato", "ducato"),
    _family("mercedes-benz", "sprinter", "sprinter"),
    _family("volkswagen", "crafter", "crafter"),
)

# People-movers that share a name with a van family. They are not N1 panel vans.
PASSENGER_NAME_TOKENS: tuple[str, ...] = (
    "tourneo",
    "caravelle",
    "california",
    "multivan",
    "traveller",
    "spaceclass",
    "spaceliner",
)

# Ordinary passenger cars. Presence rejects the listing from the van universe.
PASSENGER_CAR_TOKENS: tuple[str, ...] = (
    "golf",
    "polo",
    "passat",
    "focus",
    "fiesta",
    "corsa",
    "astra",
    "insignia",
    "qashqai",
    "juke",
    "yaris",
    "corolla",
    "prius",
    "3 series",
    "5 series",
    "a-class",
    "c-class",
    "e-class",
    "octavia",
    "superb",
    "megane",
    "clio",
    "208",
    "308",
    "2008",
    "3008",
)

PARTS_TOKENS: tuple[str, ...] = (
    "for parts",
    "spares or repair",
    "engine only",
    "gearbox only",
    "breaking",
    "breaker",
)

MANUFACTURER_ALIASES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("mercedes-benz", "mercedes benz", "mercedes"), "mercedes-benz"),
    (("volkswagen", "vw"), "volkswagen"),
    (("citroen", "citroën"), "citroen"),
    (("vauxhall",), "vauxhall"),
    (("opel",), "opel"),
    (("peugeot",), "peugeot"),
    (("renault",), "renault"),
    (("fiat",), "fiat"),
    (("nissan",), "nissan"),
    (("toyota",), "toyota"),
    (("ford",), "ford"),
)

# WMI prefixes are a consistency hint only. European VINs do not use the
# North-American check digit, so a failed US check digit is not a rejection.
WMI_MANUFACTURER: dict[str, str] = {
    "WF0": "ford",
    "WF1": "ford",
    "WVW": "volkswagen",
    "WVG": "volkswagen",
    "WV1": "volkswagen",
    "WV2": "volkswagen",
    "VF3": "peugeot",
    "VF7": "citroen",
    "VF1": "renault",
    "WDB": "mercedes-benz",
    "WDF": "mercedes-benz",
    "VSK": "nissan",
    "VNV": "nissan",
    "NMT": "toyota",
    "ZFA": "fiat",
    "W0L": "opel",
    "W0V": "opel",
}
