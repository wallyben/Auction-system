"""Robust statistics for valuation. No naive means of mixed evidence."""

from __future__ import annotations

from decimal import Decimal

from app.core.money import ZERO, as_decimal, money


def median(values: list[Decimal]) -> Decimal:
    if not values:
        raise ValueError("median requires values")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return money((ordered[mid - 1] + ordered[mid]) / Decimal("2"))


def mad(values: list[Decimal]) -> Decimal:
    if not values:
        return ZERO
    med = median(values)
    deviations = [abs(value - med) for value in values]
    return median(deviations)


def reject_outliers(values: list[Decimal], *, z: Decimal = Decimal("3.5")) -> tuple[list[Decimal], list[Decimal]]:
    """Split inliers/outliers using MAD. Conservative: keep all if MAD is 0."""
    if len(values) < 4:
        return values, []
    med = median(values)
    spread = mad(values)
    if spread == ZERO:
        return values, []
    kept: list[Decimal] = []
    rejected: list[Decimal] = []
    scale = Decimal("1.4826")
    for value in values:
        score = abs(value - med) / (scale * spread)
        if score > z:
            rejected.append(value)
        else:
            kept.append(value)
    return (kept or values), (rejected if kept else [])


def weighted_median(pairs: list[tuple[Decimal, Decimal]]) -> Decimal:
    """pairs of (value, weight)."""
    cleaned = [(as_decimal(v), as_decimal(w)) for v, w in pairs if as_decimal(w) > ZERO]
    if not cleaned:
        raise ValueError("weighted_median requires positive weights")
    cleaned.sort(key=lambda item: item[0])
    total = sum(weight for _, weight in cleaned)
    target = total / Decimal("2")
    running = ZERO
    last = cleaned[0][0]
    for value, weight in cleaned:
        running += weight
        last = value
        if running >= target:
            return money(value)
    return money(last)


def recency_weight(age_days: int) -> Decimal:
    if age_days <= 14:
        return Decimal("1.00")
    if age_days <= 45:
        return Decimal("0.80")
    if age_days <= 90:
        return Decimal("0.55")
    if age_days <= 180:
        return Decimal("0.30")
    return Decimal("0.10")


def percentile(values: list[Decimal], p: Decimal) -> Decimal:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = (len(ordered) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    frac = idx - lo
    return money(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)


def display_money(value: Decimal, *, confidence: Decimal) -> Decimal:
    """Do not print false precision when evidence is thin."""
    if confidence < Decimal("0.40"):
        return money(value).quantize(Decimal("10"))
    if confidence < Decimal("0.70"):
        return money(value).quantize(Decimal("1"))
    return money(value)
