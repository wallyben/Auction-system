"""Age and mileage effects from asking prices. A singular fit adjusts nothing."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from app.domains.vehicles.market import MarketObservation
from app.domains.vehicles.platforms import size_class

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class EffectModel:
    year_eur: Decimal
    km_eur: Decimal
    basis: str
    sample_size: int
    confidence: Decimal


def fit_effects(rows: list[MarketObservation], family: str) -> EffectModel:
    """Prefer a family slope, then a size class, then the whole van book."""

    usable = [row for row in rows if row.asking_price_eur is not None and row.asking_price_eur > 0 and row.year and row.mileage_km]
    family_rows = [row for row in usable if row.model_family == family]
    if len(family_rows) >= 8:
        fitted = _fit(family_rows)
        if fitted is not None:
            return _replace_basis(fitted, "family")
    cohort = size_class(family)
    class_rows = [row for row in usable if size_class(row.model_family) == cohort] if cohort != "unknown" else []
    if len(class_rows) >= 12:
        fitted = _fit(class_rows)
        if fitted is not None:
            return _replace_basis(fitted, "class")
    if len(usable) >= 20:
        fitted = _fit(usable)
        if fitted is not None:
            return _replace_basis(fitted, "global")
    return EffectModel(ZERO, ZERO, "none", len(usable), ZERO)


def _fit(rows: list[MarketObservation]) -> EffectModel | None:
    prices = [float(row.asking_price_eur) for row in rows if row.asking_price_eur is not None]
    years = [int(row.year) for row in rows if row.year is not None]
    kms = [int(row.mileage_km) for row in rows if row.mileage_km is not None]
    if len(prices) < 8 or len(set(years)) < 2 or len(set(kms)) < 2:
        return None
    centre = float(median(prices))
    if centre <= 0:
        return None
    year_coef, km_per_10k = _huber(years, kms, prices)
    if year_coef is None or km_per_10k is None:
        return None
    if year_coef < 0:
        year_coef = 0.0
    if km_per_10k > 0:
        km_per_10k = 0.0
    year_cap = 0.12 * centre
    km_cap = 0.08 * centre
    year_coef = min(year_coef, year_cap)
    km_per_10k = max(km_per_10k, -km_cap)
    confidence = min(Decimal("0.80"), (Decimal(len(rows)) / Decimal("40")).quantize(Decimal("0.01")))
    if year_coef == 0 and km_per_10k == 0:
        confidence = ZERO
    return EffectModel(
        year_eur=_cents(year_coef),
        km_eur=_cents(km_per_10k / 10000),
        basis="fitted",
        sample_size=len(rows),
        confidence=confidence,
    )


def _replace_basis(model: EffectModel, basis: str) -> EffectModel:
    return EffectModel(model.year_eur, model.km_eur, basis, model.sample_size, model.confidence)


def _cents(value: float) -> Decimal:
    return Decimal(str(round(value, 4)))


def _huber(years: list[int], kms: list[int], prices: list[float]) -> tuple[float | None, float | None]:
    n = len(prices)
    features = [(1.0, float(year - 2018), float(km) / 10000.0) for year, km in zip(years, kms, strict=True)]
    weights = [1.0] * n
    beta = [float(median(prices)), 0.0, 0.0]
    for _ in range(25):
        solved = _weighted_least_squares(features, prices, weights)
        if solved is None:
            return None, None
        beta = solved
        residuals = [prices[i] - _dot(features[i], beta) for i in range(n)]
        scale = _mad(residuals) or 1.0
        delta = 1.345 * scale
        weights = [1.0 if abs(residual) <= delta else delta / abs(residual) for residual in residuals]
    return beta[1], beta[2]


def _dot(features: tuple[float, float, float], beta: list[float]) -> float:
    return features[0] * beta[0] + features[1] * beta[1] + features[2] * beta[2]


def _mad(values: list[float]) -> float:
    centre = float(median(values))
    deviations = sorted(abs(value - centre) for value in values)
    return float(median(deviations))


def _weighted_least_squares(
    features: list[tuple[float, float, float]],
    prices: list[float],
    weights: list[float],
) -> list[float] | None:
    xtx = [[0.0, 0.0, 0.0] for _ in range(3)]
    xty = [0.0, 0.0, 0.0]
    for feature, price, weight in zip(features, prices, weights, strict=True):
        for row in range(3):
            xty[row] += weight * feature[row] * price
            for col in range(3):
                xtx[row][col] += weight * feature[row] * feature[col]
    return _solve3(xtx, xty)


def _solve3(matrix: list[list[float]], target: list[float]) -> list[float] | None:
    rows = [matrix[index][:] + [target[index]] for index in range(3)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda index: abs(rows[index][col]))
        if abs(rows[pivot][col]) < 1e-10:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        divisor = rows[col][col]
        for column in range(col, 4):
            rows[col][column] /= divisor
        for row in range(3):
            if row == col:
                continue
            factor = rows[row][col]
            for column in range(col, 4):
                rows[row][column] -= factor * rows[col][column]
    return [rows[index][3] for index in range(3)]
