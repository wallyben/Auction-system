"""Which Irish van searches to run. Auction stock comes before a rotating family list."""

from __future__ import annotations

from app.domains.vehicles.catalogue import VAN_FAMILIES

# One refresh must not walk the whole catalogue. The remainder waits for the next cursor.
DEFAULT_QUERY_BUDGET = 4


def family_queries() -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    queries: list[dict[str, str]] = []
    for family in VAN_FAMILIES:
        make = _make(family.manufacturer)
        model = family.phrases[0].title()
        key = (make.casefold(), family.family)
        if key in seen:
            continue
        seen.add(key)
        queries.append(
            {
                "make": make,
                "model": model,
                "body_type": "van",
                "reason": "common_family",
                "model_family": family.family,
            }
        )
    return queries


def plan_queries(
    auction_pairs: list[tuple[str, str]],
    *,
    cursor: int = 0,
    budget: int = DEFAULT_QUERY_BUDGET,
) -> tuple[list[dict[str, str]], int]:
    """Auction identities first, then a slice of the common-family rotation."""

    selected: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for make, model in auction_pairs:
        item = {
            "make": make.strip(),
            "model": model.strip(),
            "body_type": "van",
            "reason": "active_auction",
            "model_family": "",
        }
        key = (item["make"].casefold(), item["model"].casefold())
        if not item["make"] or not item["model"] or key in seen:
            continue
        seen.add(key)
        selected.append(item)
        if len(selected) >= budget:
            return selected, cursor

    common = family_queries()
    if not common:
        return selected, cursor
    start = cursor % len(common)
    for offset in range(len(common)):
        if len(selected) >= budget:
            break
        item = common[(start + offset) % len(common)]
        key = (item["make"].casefold(), item["model"].casefold())
        if key in seen:
            continue
        seen.add(key)
        selected.append(item)
    advanced = (start + max(budget - len(auction_pairs), 0)) % len(common)
    return selected, advanced


def _make(manufacturer: str) -> str:
    if manufacturer == "mercedes-benz":
        return "Mercedes-Benz"
    return manufacturer.replace("_", " ").title()
