"""Advertised price versus buyer cash interval. Unknown VAT is a bound, not a guess."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.money import money
from app.domains.vehicles.tax import VAT_RATE

_EXCLUSIVE = {"VAT_EXCLUSIVE", "EX_VAT", "EXCLUSIVE", "PLUS_VAT", "VAT_EXCLUSIVE_EXPLICIT"}
_INCLUSIVE = {"VAT_INCLUSIVE", "VAT_INCLUSIVE_EXPLICIT", "INC_VAT", "INCLUSIVE", "GROSS"}
_NONE = {"NO_VAT", "NO VAT"}
_MARGIN = {"MARGIN_SCHEME", "MARGIN SCHEME"}
_QUALIFYING = {"VAT_QUALIFYING", "QUALIFYING"}


@dataclass(frozen=True, slots=True)
class PriceInterval:
    advertised_eur: Decimal
    cash_low_eur: Decimal
    cash_high_eur: Decimal
    basis: str
    vat_classification: str
    exact: bool
    evidence: str

    def to_dict(self) -> dict[str, object]:
        return {
            "advertised_eur": str(self.advertised_eur),
            "cash_low_eur": str(self.cash_low_eur),
            "cash_high_eur": str(self.cash_high_eur),
            "basis": self.basis,
            "vat_classification": self.vat_classification,
            "exact": self.exact,
            "evidence": self.evidence,
        }


def normalise_vat_classification(classification: str, presentation: str = "") -> str:
    token = (classification or "").strip().upper().replace("-", "_").replace(" ", "_")
    folded = (presentation or "").strip().upper().replace("-", "_").replace(" ", "_")
    if token in _EXCLUSIVE or folded in _EXCLUSIVE or folded in {"EX_VAT"}:
        return "VAT_EXCLUSIVE"
    if token in _INCLUSIVE or folded in _INCLUSIVE or folded in {"VAT_INCLUSIVE"}:
        return "VAT_INCLUSIVE"
    if token in _NONE or folded in {"NO_VAT"}:
        return "NO_VAT"
    if token in _MARGIN or folded in {"MARGIN_SCHEME"}:
        return "MARGIN_SCHEME"
    if token in _QUALIFYING or folded in {"QUALIFYING"}:
        return "VAT_QUALIFYING"
    return "UNKNOWN"


def cash_interval(
    advertised: Decimal,
    classification: str,
    *,
    presentation: str = "",
    evidence: str = "",
) -> PriceInterval:
    """Map explicit wording to one cash price. Unknown wording stays [P, P×(1+rate)]."""

    price = money(advertised)
    kind = normalise_vat_classification(classification, presentation)
    gross = money(price * (Decimal("1") + VAT_RATE))
    if kind == "VAT_EXCLUSIVE":
        return PriceInterval(price, gross, gross, "VAT_EXCLUSIVE_EXPLICIT", kind, True, evidence or "explicit VAT exclusive")
    if kind == "VAT_INCLUSIVE":
        return PriceInterval(price, price, price, "VAT_INCLUSIVE_EXPLICIT", kind, True, evidence or "explicit VAT inclusive")
    if kind == "NO_VAT":
        return PriceInterval(price, price, price, "NO_VAT", kind, True, evidence or "explicit no VAT")
    if kind == "MARGIN_SCHEME":
        return PriceInterval(price, price, price, "MARGIN_SCHEME", kind, True, evidence or "explicit margin scheme cash price")
    note = "VAT qualifying without inclusive or exclusive wording" if kind == "VAT_QUALIFYING" else "VAT presentation unknown"
    return PriceInterval(price, price, gross, "VAT_UNCERTAIN", kind, False, evidence or note)
