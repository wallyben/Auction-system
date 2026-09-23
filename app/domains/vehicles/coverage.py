"""Which Irish van families can be valued from the stored asking book."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from app.domains.vehicles.market import MarketObservation

_KNOWN_VAT = {"VAT_EXCLUSIVE", "VAT_INCLUSIVE"}


def _latest_by_listing(observations: list[MarketObservation]) -> list[MarketObservation]:
    latest: dict[str, MarketObservation] = {}
    for row in observations:
        current = latest.get(row.listing_id)
        if current is None or row.observed_at >= current.observed_at:
            latest[row.listing_id] = row
    return [row for row in latest.values() if row.status.value != "DISAPPEARED"]


def classify_family(rows: list[MarketObservation]) -> str:
    priced = [row for row in rows if row.asking_price_eur is not None and row.asking_price_eur > 0]
    known = [row for row in priced if row.vat_classification in _KNOWN_VAT]
    years = {row.year for row in priced if row.year}
    mileaged = [row for row in priced if row.mileage_km]
    if not priced:
        return "NONE"
    if len(priced) >= 8 and len(known) >= 5 and len(years) >= 2 and len(mileaged) >= 5:
        return "GOOD_COVERAGE"
    if len(priced) >= 5:
        return "MODERATE_COVERAGE"
    return "THIN"


def coverage_report(observations: list[MarketObservation]) -> list[dict[str, object]]:
    grouped: dict[str, list[MarketObservation]] = defaultdict(list)
    for row in _latest_by_listing(observations):
        grouped[row.model_family].append(row)
    report = []
    for family, rows in sorted(grouped.items()):
        priced = [row for row in rows if row.asking_price_eur is not None and row.asking_price_eur > 0]
        years = sorted({row.year for row in priced if row.year})
        miles = [row.mileage_km for row in priced if row.mileage_km]
        report.append(
            {
                "family": family,
                "active_listings": len(rows),
                "listings_with_prices": len(priced),
                "listings_with_usable_vat": sum(1 for row in priced if row.vat_classification in _KNOWN_VAT),
                "year_min": years[0] if years else None,
                "year_max": years[-1] if years else None,
                "mileage_min": min(miles) if miles else None,
                "mileage_max": max(miles) if miles else None,
                "coverage": classify_family(rows),
            }
        )
    return report


def identity_completeness(observations: list[MarketObservation]) -> dict[str, object]:
    active = _latest_by_listing(observations)
    total = len(active)

    def present(predicate) -> int:
        return sum(1 for row in active if predicate(row))

    def rate(count: int) -> str:
        if total == 0:
            return "0"
        return str((Decimal(count) / Decimal(total)).quantize(Decimal("0.001")))

    counts = {
        "listings": total,
        "family": present(lambda row: bool(row.model_family)),
        "year": present(lambda row: row.year is not None),
        "mileage": present(lambda row: row.mileage_km is not None),
        "fuel": present(lambda row: row.fuel.value != "UNKNOWN"),
        "transmission": present(lambda row: bool(row.transmission)),
        "wheelbase": present(lambda row: bool(row.wheelbase)),
        "roof": present(lambda row: bool(row.roof)),
        "derivative": present(lambda row: bool(row.derivative)),
    }
    return {key: {"count": value, "share": rate(value)} if key != "listings" else value for key, value in counts.items()}
