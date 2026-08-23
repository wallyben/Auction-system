"""Compare Irish and nearby exit channels. There is no single Irish resale price."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.core.money import ZERO, money
from app.exits.fees import FEE_SCHEDULE, fee_for
from app.shipping.engine import estimate_outbound


@dataclass(slots=True)
class ExitQuote:
    channel: str
    gross_expected_sale: Decimal
    expected_fee: Decimal
    payment_fee: Decimal
    shipping: Decimal
    returns_allowance: Decimal
    expected_days: int
    confidence: Decimal
    net_proceeds: Decimal
    notes: str


@dataclass(slots=True)
class ExitComparison:
    quotes: list[ExitQuote]
    best_expected_exit: str
    fastest_exit: str
    safest_exit: str
    highest_net_exit: str
    liquidation_exit: str


_GROSS_HAIRCUT = {
    "ebay_ie": Decimal("1.00"),
    "ebay_gb": Decimal("0.96"),
    "local_ie": Decimal("0.90"),
    "cardmarket": Decimal("0.98"),
    "discogs": Decimal("0.97"),
    "reverb": Decimal("0.97"),
    "cex_trade_in": Decimal("0.62"),
    "auction_ie": Decimal("0.88"),
    "dealer": Decimal("0.70"),
}

_DAYS = {
    "ebay_ie": 18,
    "ebay_gb": 22,
    "local_ie": 12,
    "cardmarket": 16,
    "discogs": 20,
    "reverb": 20,
    "cex_trade_in": 1,
    "auction_ie": 28,
    "dealer": 3,
}

_SAFE = {
    "ebay_ie": Decimal("0.70"),
    "ebay_gb": Decimal("0.62"),
    "local_ie": Decimal("0.45"),
    "cardmarket": Decimal("0.72"),
    "discogs": Decimal("0.68"),
    "reverb": Decimal("0.68"),
    "cex_trade_in": Decimal("0.90"),
    "auction_ie": Decimal("0.50"),
    "dealer": Decimal("0.80"),
}


def _channels_for(category: str | None) -> list[str]:
    base = ["ebay_ie", "ebay_gb", "local_ie", "dealer"]
    if category == "trading_cards":
        return ["cardmarket", "ebay_ie", "local_ie"]
    if category in {"music_dj", "pro_av"}:
        return ["reverb", "ebay_ie", "local_ie", "dealer"]
    if category == "gaming":
        return ["ebay_ie", "local_ie", "cex_trade_in", "dealer"]
    return base


def compare_exits(
    *,
    expected_sale_eur: Decimal,
    category: str | None,
    weight_kg: Decimal | None = None,
    returns_rate: Decimal = Decimal("0.03"),
) -> ExitComparison:
    quotes: list[ExitQuote] = []
    for channel in _channels_for(category):
        rule = fee_for(channel, category)
        gross = money(expected_sale_eur * _GROSS_HAIRCUT[channel])
        fee = money(gross * rule.percent * (Decimal("1") + rule.vat_on_fee) + rule.fixed_eur)
        pay = money(gross * rule.payment_percent + rule.payment_fixed)
        ship = estimate_outbound(category=category, channel=channel, weight_kg=weight_kg)
        returns = money(gross * returns_rate) if channel not in {"cex_trade_in", "dealer", "local_ie"} else ZERO
        net = money(gross - fee - pay - ship.amount_eur - returns)
        quotes.append(
            ExitQuote(
                channel=channel,
                gross_expected_sale=gross,
                expected_fee=fee,
                payment_fee=pay,
                shipping=ship.amount_eur,
                returns_allowance=returns,
                expected_days=_DAYS[channel],
                confidence=_SAFE[channel],
                net_proceeds=net,
                notes=rule.notes,
            )
        )
    if not quotes:
        raise ValueError("No exit channels")
    best = max(quotes, key=lambda q: q.net_proceeds * q.confidence)
    fastest = min(quotes, key=lambda q: q.expected_days)
    safest = max(quotes, key=lambda q: q.confidence)
    highest = max(quotes, key=lambda q: q.net_proceeds)
    liq = next((q for q in quotes if q.channel in {"cex_trade_in", "dealer"}), safest)
    return ExitComparison(
        quotes=quotes,
        best_expected_exit=best.channel,
        fastest_exit=fastest.channel,
        safest_exit=safest.channel,
        highest_net_exit=highest.channel,
        liquidation_exit=liq.channel,
    )


class ExitChannelEngine:
    compare = staticmethod(compare_exits)
    schedule = FEE_SCHEDULE
