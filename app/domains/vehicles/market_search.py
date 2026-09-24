"""Market groups and Brave query plans. Search the group, not the lot."""

from __future__ import annotations

from dataclasses import dataclass

from app.domains.vehicles.platforms import sibling_families

QUERY_VERSION = "market-search-1"

# Canonical Irish commercial families. Aliases are query text, not extra models.
FAMILIES: dict[str, dict[str, object]] = {
    "transit": {"make": "Ford", "label": "Ford Transit", "exclude": ("Custom", "Connect")},
    "transit_custom": {"make": "Ford", "label": "Ford Transit Custom", "exclude": ()},
    "transit_connect": {"make": "Ford", "label": "Ford Transit Connect", "exclude": ()},
    "berlingo": {"make": "Citroen", "label": "Citroen Berlingo", "exclude": ()},
    "dispatch": {"make": "Citroen", "label": "Citroen Dispatch", "exclude": ()},
    "relay": {"make": "Citroen", "label": "Citroen Relay", "exclude": ()},
    "partner": {"make": "Peugeot", "label": "Peugeot Partner", "exclude": ()},
    "expert": {"make": "Peugeot", "label": "Peugeot Expert", "exclude": ()},
    "boxer": {"make": "Peugeot", "label": "Peugeot Boxer", "exclude": ()},
    "combo": {"make": "Vauxhall", "label": "Vauxhall Combo", "aliases": ("Opel Combo",), "exclude": ()},
    "vivaro": {"make": "Vauxhall", "label": "Vauxhall Vivaro", "aliases": ("Opel Vivaro",), "exclude": ()},
    "movano": {"make": "Vauxhall", "label": "Vauxhall Movano", "aliases": ("Opel Movano",), "exclude": ()},
    "kangoo": {"make": "Renault", "label": "Renault Kangoo", "exclude": ()},
    "trafic": {"make": "Renault", "label": "Renault Trafic", "exclude": ()},
    "master": {"make": "Renault", "label": "Renault Master", "exclude": ()},
    "primastar": {"make": "Nissan", "label": "Nissan Primastar", "exclude": ()},
    "interstar": {"make": "Nissan", "label": "Nissan Interstar", "exclude": ()},
    "caddy": {"make": "Volkswagen", "label": "Volkswagen Caddy", "exclude": ()},
    "transporter": {"make": "Volkswagen", "label": "Volkswagen Transporter", "exclude": ()},
    "crafter": {"make": "Volkswagen", "label": "Volkswagen Crafter", "exclude": ()},
    "sprinter": {"make": "Mercedes", "label": "Mercedes Sprinter", "exclude": ()},
    "vito": {"make": "Mercedes", "label": "Mercedes Vito", "exclude": ()},
    "proace": {"make": "Toyota", "label": "Toyota Proace", "exclude": ("City",)},
    "proace_city": {"make": "Toyota", "label": "Toyota Proace City", "exclude": ()},
    "doblo": {"make": "Fiat", "label": "Fiat Doblo", "exclude": ()},
    "ducato": {"make": "Fiat", "label": "Fiat Ducato", "exclude": ()},
}

_DOMAINS = (
    ("donedeal.ie", "brave-donedeal-index-1"),
    ("carsireland.ie", "brave-carsireland-index-1"),
    ("carzone.ie", "brave-carzone-index-1"),
)
_BODY_WORD = {
    "PANEL": "panel van",
    "CREW": "crew van",
    "TIPPER": "tipper",
    "DROPSIDE": "dropside",
    "LUTON": "luton",
    "CHASSIS": "chassis cab",
    "MINIBUS": "minibus",
}


@dataclass(frozen=True, slots=True)
class MarketGroup:
    group_id: str
    model_family: str
    body: str
    year_from: int
    year_to: int
    fuel: str
    label: str

    def to_dict(self) -> dict[str, object]:
        return {
            "group_id": self.group_id,
            "model_family": self.model_family,
            "body": self.body,
            "year_from": self.year_from,
            "year_to": self.year_to,
            "fuel": self.fuel,
            "label": self.label,
        }


@dataclass(frozen=True, slots=True)
class SearchQuery:
    strategy: str
    text: str
    domain: str
    source_id: str
    model_family: str
    adjustment_only: bool
    group_id: str


def family_label(model_family: str) -> str:
    row = FAMILIES.get(model_family) or {}
    return str(row.get("label") or model_family.replace("_", " "))


def group_for(model_family: str, year: int | None, body: str = "PANEL", fuel: str = "DIESEL") -> MarketGroup | None:
    if not model_family or model_family not in FAMILIES or year is None:
        return None
    start = year - 1
    end = year + 1
    body_name = (body or "PANEL").upper()
    fuel_name = fuel if fuel and fuel != "UNKNOWN" else "ANY"
    label = family_label(model_family)
    group_id = f"{model_family}|{body_name}|{start}-{end}|{fuel_name}"
    return MarketGroup(group_id, model_family, body_name, start, end, fuel_name, f"{label} {body_name} {start}-{end}")


def groups_for_lots(lots: list[dict[str, object]]) -> list[MarketGroup]:
    """Collapse nearby lots of one family into overlapping year windows."""

    buckets: dict[tuple[str, str, str], list[int]] = {}
    for lot in lots:
        family = str(lot.get("model_family") or "")
        year = lot.get("year")
        if family not in FAMILIES or not isinstance(year, int):
            continue
        body = str(lot.get("body") or "PANEL").upper()
        fuel = str(lot.get("fuel") or "ANY")
        if fuel == "UNKNOWN":
            fuel = "ANY"
        buckets.setdefault((family, body, fuel), []).append(year)
    groups: list[MarketGroup] = []
    for (family, body, fuel), years in buckets.items():
        span = max(years) - min(years)
        if span <= 3:
            anchor = min(years)
            groups.append(group_for(family, anchor, body, fuel) or _window(family, body, fuel, min(years) - 1, max(years) + 1))
            if max(years) - anchor > 2:
                groups.append(_window(family, body, fuel, max(years) - 1, max(years) + 1))
        else:
            for year in sorted(set(years)):
                item = group_for(family, year, body, fuel)
                if item and item.group_id not in {row.group_id for row in groups}:
                    groups.append(item)
    return groups


def queries_for(group: MarketGroup, strategy: str) -> list[SearchQuery]:
    spec = FAMILIES.get(group.model_family) or {}
    label = str(spec.get("label") or group.model_family)
    years = _years(group, strategy)
    body = _BODY_WORD.get(group.body, "van")
    built: list[SearchQuery] = []
    phrases = [label]
    if strategy == "strategy-3":
        phrases.extend(str(alias) for alias in spec.get("aliases") or ())
        for sibling in sorted(sibling_families(group.model_family)):
            phrases.append(family_label(sibling))
    for phrase in phrases:
        adjustment = phrase != label
        for year in years:
            for domain, source_id in _DOMAINS:
                text = _compose(strategy, phrase, year, body, domain)
                built.append(
                    SearchQuery(strategy, text, domain, source_id, group.model_family, adjustment, group.group_id)
                )
        if strategy == "strategy-3":
            built.append(
                SearchQuery(
                    strategy,
                    f"\"{phrase}\" \"{years[0]}\" van Ireland dealer",
                    "",
                    "brave-dealer-index-1",
                    group.model_family,
                    adjustment,
                    group.group_id,
                )
            )
    return built


def vat_queries(group: MarketGroup) -> list[SearchQuery]:
    label = family_label(group.model_family)
    year = group.year_from + 1
    rows: list[SearchQuery] = []
    for phrase in ("+ VAT", "inc VAT", "no VAT"):
        for domain, source_id in _DOMAINS:
            text = f'site:{domain} "{label}" "{year}" "{phrase}"'
            rows.append(SearchQuery("vat", text, domain, source_id, group.model_family, False, group.group_id))
    return rows


def _window(family: str, body: str, fuel: str, start: int, end: int) -> MarketGroup:
    label = family_label(family)
    group_id = f"{family}|{body}|{start}-{end}|{fuel}"
    return MarketGroup(group_id, family, body, start, end, fuel, f"{label} {body} {start}-{end}")


def _years(group: MarketGroup, strategy: str) -> tuple[int, ...]:
    centre = group.year_from + 1
    if strategy == "strategy-1":
        return (centre,)
    return (group.year_from, centre, group.year_to)


def _compose(strategy: str, phrase: str, year: int, body: str, domain: str) -> str:
    if strategy == "strategy-1":
        return f'site:{domain} "{phrase}" "{year}"'
    if strategy == "strategy-2":
        return f'site:{domain} "{phrase}" "{year}" "{body}"'
    return f'site:{domain} "{phrase}" "{year}" "{body}" "+ VAT"'
