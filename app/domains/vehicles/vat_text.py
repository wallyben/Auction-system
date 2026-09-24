"""Explicit VAT wording only. A commercial van is not evidence of VAT treatment."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

PARSER_VERSION = "vat-text-1"

_EXCLUSIVE = (
    re.compile(r"\+\s*vat\b", re.I),
    re.compile(r"\bplus\s+vat\b", re.I),
    re.compile(r"\bexcluding\s+vat\b", re.I),
    re.compile(r"\bex\.?\s*vat\b", re.I),
    re.compile(r"\bvat\s+exclusive\b", re.I),
    re.compile(r"\bprice\s+excluding\s+vat\b", re.I),
)
_INCLUSIVE = (
    re.compile(r"\bvat\s+inclusive\b", re.I),
    re.compile(r"\bincluding\s+vat\b", re.I),
    re.compile(r"\bincludes\s+vat\b", re.I),
    re.compile(r"\binc\.?\s*vat\b", re.I),
    re.compile(r"\bprice\s+includes\s+vat\b", re.I),
)
_QUALIFYING = (
    re.compile(r"\bvat\s+invoice\b", re.I),
    re.compile(r"\bvat\s+qualifying\b", re.I),
)
_MARGIN = (
    re.compile(r"\bmargin\s+scheme\b", re.I),
    re.compile(r"\bvat\s+margin\b", re.I),
)
_NONE = (
    re.compile(r"\bno\s+vat\b", re.I),
    re.compile(r"\bvat\s+not\s+applicable\b", re.I),
)
_RECLAIM = (
    re.compile(r"\bvat\s+reclaimable\b", re.I),
    re.compile(r"\bvat\s+qualifying\b", re.I),
)
_RATE = re.compile(r"\b23\s*%")
_PHONE = re.compile(r"\b(?:\+?\d[\d\s/()-]{7,}\d)\b")


@dataclass(frozen=True, slots=True)
class VatReading:
    classification: str
    fragment: str
    parser_version: str
    confidence: Decimal

    def presentation(self) -> str:
        return {
            "VAT_EXCLUSIVE": "ex_vat",
            "VAT_INCLUSIVE": "vat_inclusive",
            "VAT_QUALIFYING": "qualifying",
            "MARGIN_SCHEME": "margin_scheme",
            "NO_VAT": "no_vat",
        }.get(self.classification, "unknown")


def classify_vat_text(*parts: str) -> VatReading:
    text = " ".join(part for part in parts if part).strip()
    if not text:
        return VatReading("UNKNOWN", "", PARSER_VERSION, Decimal("0"))
    exclusive = _fragment(text, _EXCLUSIVE)
    inclusive = _fragment(text, _INCLUSIVE)
    qualifying = _fragment(text, _QUALIFYING) or _fragment(text, _RECLAIM)
    margin = _fragment(text, _MARGIN)
    none = _fragment(text, _NONE)
    if exclusive and inclusive:
        return VatReading("UNKNOWN", _redact(exclusive), PARSER_VERSION, Decimal("0.2"))
    if exclusive:
        confidence = Decimal("0.95") if _RATE.search(exclusive) else Decimal("0.9")
        return VatReading("VAT_EXCLUSIVE", _redact(exclusive), PARSER_VERSION, confidence)
    if inclusive:
        confidence = Decimal("0.95") if _RATE.search(inclusive) else Decimal("0.85")
        return VatReading("VAT_INCLUSIVE", _redact(inclusive), PARSER_VERSION, confidence)
    if none and not (exclusive or inclusive):
        return VatReading("NO_VAT", _redact(none), PARSER_VERSION, Decimal("0.9"))
    if margin:
        return VatReading("MARGIN_SCHEME", _redact(margin), PARSER_VERSION, Decimal("0.9"))
    if qualifying:
        return VatReading("VAT_QUALIFYING", _redact(qualifying), PARSER_VERSION, Decimal("0.7"))
    return VatReading("UNKNOWN", "", PARSER_VERSION, Decimal("0"))


def price_basis(advertised: Decimal | None, classification: str, fragment: str) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Return net, gross, and VAT rate. The advertised figure is not overwritten."""

    if advertised is None:
        return None, None, None
    if re.search(r"\b(?:9|13\.5|13,5)\s*%", fragment or ""):
        return None, None, None
    if classification == "VAT_EXCLUSIVE":
        gross = (advertised * Decimal("1.23")).quantize(Decimal("0.01"))
        return advertised, gross, Decimal("0.23")
    if classification == "VAT_INCLUSIVE" and _RATE.search(fragment or ""):
        net = (advertised / Decimal("1.23")).quantize(Decimal("0.01"))
        return net, advertised, Decimal("0.23")
    if classification == "VAT_INCLUSIVE":
        return None, advertised, None
    return None, None, None


def _fragment(text: str, patterns: tuple[re.Pattern[str], ...]) -> str:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            start = max(0, match.start() - 24)
            end = min(len(text), match.end() + 24)
            return " ".join(text[start:end].split())
    return ""


def _redact(fragment: str) -> str:
    return _PHONE.sub("[redacted]", fragment)[:180]
