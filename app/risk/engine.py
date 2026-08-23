"""Risk engine. Cheap listings get more suspicion, not a higher score."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.models.enums import IdentityLevel


@dataclass(slots=True)
class RiskFlag:
    code: str
    severity: str
    detail: str


@dataclass(slots=True)
class RiskResult:
    score: Decimal
    flags: list[RiskFlag] = field(default_factory=list)
    high: bool = False


def assess_risk(
    *,
    title: str,
    identity_level: IdentityLevel,
    identity_confidence: Decimal,
    condition_confidence: Decimal,
    valuation_confidence: Decimal,
    asking_eur: Decimal | None,
    expected_sale_eur: Decimal,
    seller: str | None,
    images: list[str],
    is_lot: bool,
) -> RiskResult:
    flags: list[RiskFlag] = []
    score = Decimal("0.15")
    blob = title.lower()
    if identity_level in {IdentityLevel.UNKNOWN, IdentityLevel.CATEGORY}:
        flags.append(RiskFlag("weak_identity", "high", "Product is not identified tightly enough to buy."))
        score += Decimal("0.25")
    if identity_confidence < Decimal("0.50"):
        flags.append(RiskFlag("identity_confidence", "high", "Identity confidence below 0.50."))
        score += Decimal("0.15")
    if condition_confidence < Decimal("0.40"):
        flags.append(RiskFlag("condition_unknown", "medium", "Condition is weakly evidenced."))
        score += Decimal("0.10")
    if valuation_confidence < Decimal("0.45"):
        flags.append(RiskFlag("thin_comps", "high", "Valuation evidence is too thin."))
        score += Decimal("0.15")
    if asking_eur and expected_sale_eur and asking_eur < expected_sale_eur * Decimal("0.40"):
        flags.append(RiskFlag("too_cheap", "high", "Ask is far below estimated resale. Treat as a trap until proven."))
        score += Decimal("0.20")
    if any(word in blob for word in ("replica", "homage", "style", "not genuine", "aaa")):
        flags.append(RiskFlag("counterfeit_language", "high", "Listing language suggests replica/non-genuine goods."))
        score += Decimal("0.35")
    if not images:
        flags.append(RiskFlag("no_images", "medium", "No images supplied by source."))
        score += Decimal("0.08")
    if is_lot:
        flags.append(RiskFlag("lot", "medium", "Job lot: residue and labour risk."))
        score += Decimal("0.10")
    if seller and seller.lower() in {"unknown", ""}:
        flags.append(RiskFlag("unknown_seller", "low", "Seller identity missing."))
        score += Decimal("0.05")
    if any(word in blob for word in ("cash only", "whatsapp only", "outside ebay", "off platform")):
        flags.append(RiskFlag("off_platform_payment", "high", "Payment outside platform."))
        score += Decimal("0.25")
    if any(word in blob for word in ("serial removed", "serial obscured", "no serial")):
        flags.append(RiskFlag("serial_obscured", "high", "Serial number hidden."))
        score += Decimal("0.20")
    if "stock photo" in blob or "catalogue image" in blob:
        flags.append(RiskFlag("stock_photos", "medium", "Stock photos only."))
        score += Decimal("0.12")
    if asking_eur and asking_eur < Decimal("30") and expected_sale_eur and expected_sale_eur > Decimal("200"):
        flags.append(RiskFlag("shipping_trap_or_fraud", "high", "Tiny ask vs high expected sale."))
        score += Decimal("0.20")
    high = any(flag.severity == "high" for flag in flags)
    if score > Decimal("0.99"):
        score = Decimal("0.99")
    return RiskResult(score=score, flags=flags, high=high)
