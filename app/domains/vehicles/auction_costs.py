"""Versioned auction fee schedules. A missing schedule does not become a zero fee."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.core.money import ZERO, money
from app.domains.vehicles.enums import AuctionVatTreatment, EvidencePosture
from app.domains.vehicles.evidence import MoneyLine
from app.domains.vehicles.tax import VAT_RATE


@dataclass(frozen=True, slots=True)
class PremiumBand:
    """Rate applied to the whole hammer when the hammer is at or below ``up_to``."""

    up_to_eur: Decimal | None
    percent: Decimal


@dataclass(frozen=True, slots=True)
class AuctionFeeSchedule:
    schedule_id: str
    source_id: str
    version: str
    effective_from: datetime
    retrieved_at: datetime
    evidence_url: str
    applies_to: str
    bands: tuple[PremiumBand, ...]
    minimum_premium_eur: Decimal
    premium_vat_rate: Decimal | None
    documentation_fee_eur: Decimal
    online_bidding_fee_eur: Decimal
    collection_fee_eur: Decimal

    def usable_for_vans(self) -> bool:
        return self.applies_to == "commercial_vehicles" and bool(self.bands) and self.premium_vat_rate is not None


def buyer_premium(schedule: AuctionFeeSchedule, hammer: Decimal) -> Decimal:
    selected = schedule.bands[-1]
    for band in schedule.bands:
        if band.up_to_eur is None or hammer <= band.up_to_eur:
            selected = band
            break
    return money(max(hammer * selected.percent, schedule.minimum_premium_eur))


@dataclass(frozen=True, slots=True)
class AuctionCostResult:
    hammer_eur: Decimal
    blocked: bool
    lines: tuple[MoneyLine, ...]
    economic_total_eur: Decimal | None

    def amount(self, name: str) -> Decimal | None:
        for line in self.lines:
            if line.name == name:
                return line.amount_eur
        return None


def auction_costs(
    *,
    hammer_eur: Decimal,
    schedule: AuctionFeeSchedule | None,
    vat_treatment: AuctionVatTreatment,
    hammer_is_vat_inclusive: bool | None,
    owner_vat_registered: bool,
    commercial_vat_invoice_expected: bool,
    payment_fee_eur: Decimal | None,
    payment_fee_posture: EvidencePosture,
) -> AuctionCostResult:
    lines: list[MoneyLine] = [
        MoneyLine("hammer", money(hammer_eur), EvidencePosture.PROVEN, "bid", "Hammer in EUR"),
    ]
    blocked = False
    if schedule is None or not schedule.usable_for_vans():
        lines.append(
            MoneyLine(
                "buyer_premium",
                None,
                EvidencePosture.UNKNOWN,
                "fee_schedule",
                "No commercial-vehicle fee schedule is loaded for this source.",
            )
        )
        blocked = True
        premium = None
        premium_vat = None
    else:
        premium = buyer_premium(schedule, hammer_eur)
        assert schedule.premium_vat_rate is not None
        premium_vat = money(premium * schedule.premium_vat_rate)
        source = f"{schedule.source_id}:{schedule.version}"
        lines.extend(
            [
                MoneyLine("buyer_premium", premium, EvidencePosture.PROVEN, source, schedule.evidence_url),
                MoneyLine("premium_vat", premium_vat, EvidencePosture.PROVEN, source, "VAT on the buyer's premium"),
                MoneyLine("documentation_fee", money(schedule.documentation_fee_eur), EvidencePosture.PROVEN, source, ""),
                MoneyLine("online_bidding_fee", money(schedule.online_bidding_fee_eur), EvidencePosture.PROVEN, source, ""),
                MoneyLine("collection_fee", money(schedule.collection_fee_eur), EvidencePosture.PROVEN, source, ""),
            ]
        )

    lot_vat_cash: Decimal | None
    lot_vat_economic: Decimal | None
    if vat_treatment is AuctionVatTreatment.UNKNOWN or hammer_is_vat_inclusive is None:
        lot_vat_cash = None
        lot_vat_economic = None
        lines.append(
            MoneyLine(
                "auction_lot_vat",
                None,
                EvidencePosture.UNKNOWN,
                "listing",
                "Lot VAT treatment or whether the hammer includes VAT is unknown.",
            )
        )
        blocked = True
    elif vat_treatment is AuctionVatTreatment.NO_VAT or vat_treatment is AuctionVatTreatment.MARGIN_SCHEME:
        lot_vat_cash = ZERO
        lot_vat_economic = ZERO
        note = "No VAT is added to the hammer." if vat_treatment is AuctionVatTreatment.NO_VAT else "Margin scheme: VAT is not added to the hammer and is not modelled as recoverable."
        lines.append(MoneyLine("auction_lot_vat", ZERO, EvidencePosture.PROVEN, vat_treatment.value, note))
    elif hammer_is_vat_inclusive:
        # Cash already includes VAT. Economic cost removes it only when recovery is supported.
        if owner_vat_registered and commercial_vat_invoice_expected:
            extracted = money(hammer_eur - (hammer_eur / (Decimal("1") + VAT_RATE)))
            lot_vat_cash = ZERO
            lot_vat_economic = money(ZERO - extracted)
            lines.append(
                MoneyLine(
                    "auction_lot_vat",
                    lot_vat_economic,
                    EvidencePosture.ESTIMATED,
                    "inclusive_hammer",
                    "VAT-inclusive hammer. Input VAT is subtracted because a VAT invoice is expected.",
                )
            )
        else:
            lot_vat_cash = ZERO
            lot_vat_economic = ZERO
            lines.append(
                MoneyLine(
                    "auction_lot_vat",
                    ZERO,
                    EvidencePosture.PROVEN,
                    "inclusive_hammer",
                    "VAT-inclusive hammer. Input VAT is not subtracted.",
                )
            )
    else:
        lot_vat_cash = money(hammer_eur * VAT_RATE)
        if owner_vat_registered and commercial_vat_invoice_expected:
            lot_vat_economic = ZERO
            note = "Standard-rated hammer. Input VAT is treated as recoverable for a VAT-registered buyer with an invoice."
        else:
            lot_vat_economic = lot_vat_cash
            note = "Standard-rated hammer. VAT is a cash cost."
        lines.append(MoneyLine("auction_lot_vat", lot_vat_economic, EvidencePosture.ESTIMATED if lot_vat_economic == ZERO else EvidencePosture.PROVEN, vat_treatment.value, note))
        lines.append(MoneyLine("auction_lot_vat_cash", lot_vat_cash, EvidencePosture.PROVEN, vat_treatment.value, "Cash VAT on the hammer"))

    if premium is not None and premium_vat is not None and owner_vat_registered and commercial_vat_invoice_expected:
        lines.append(
            MoneyLine(
                "premium_vat_recovery",
                money(ZERO - premium_vat),
                EvidencePosture.ESTIMATED,
                "owner_vat_registered",
                "Premium VAT treated as recoverable input VAT.",
            )
        )

    lines.append(
        MoneyLine(
            "payment_fee",
            None if payment_fee_posture is EvidencePosture.UNKNOWN else payment_fee_eur,
            payment_fee_posture,
            "payment_rail",
            "Payment fee must be stated, including zero when the rail charges nothing.",
        )
    )
    if payment_fee_posture is EvidencePosture.UNKNOWN or payment_fee_eur is None:
        blocked = True

    economic: Decimal | None = None
    if not blocked:
        economic = ZERO
        for line in lines:
            if line.name == "auction_lot_vat_cash":
                continue
            if line.amount_eur is None:
                economic = None
                break
            economic += line.amount_eur
        if economic is not None:
            economic = money(economic)
    return AuctionCostResult(
        hammer_eur=money(hammer_eur),
        blocked=blocked,
        lines=tuple(lines),
        economic_total_eur=economic,
    )
