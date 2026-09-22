"""Configured ARIE-CV thresholds.

These are owner policy, not tax law. Tax rates live in ``tax.py`` with
Revenue citations. Changing a threshold here does not certify a vehicle.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

# Retrieved from Revenue.ie on this date. Stale rules must not price a bid.
TAX_RULE_VERSION = "ie-cv-tax-2026-09-22"
TAX_RULES_RETRIEVED_AT = datetime(2026, 9, 22, tzinfo=timezone.utc)
TAX_RULE_MAX_AGE_DAYS = 120

MARKET_FRESH_DAYS = 14
MOT_HISTORY_MAX_AGE_DAYS = 400
FX_MAX_AGE_DAYS = 3

# Asking prices are not sold prices. Without enough realised sales the
# achievable value is an asking price haircut, and confidence is capped.
ASKING_TO_ACHIEVABLE_DISCOUNT = Decimal("0.15")
ASKING_ONLY_CONFIDENCE_CAP = Decimal("0.62")
VALUATION_CONFIDENCE_MIN = Decimal("0.60")
MIN_ELIGIBLE_COMPS = 8
MIN_CLOSE_COMPS = 5
MIN_REALISED_FOR_UNCAPPED_CONFIDENCE = 3

# Identity score: comps below this are rejected. Close comps support the book.
COMP_MIN_SCORE = 55
COMP_CLOSE_SCORE = 75

REQUIRED_ABSOLUTE_PROFIT_EUR = Decimal("800")
REQUIRED_ROI = Decimal("0.15")
MIN_DOWNSIDE_PROFIT_EUR = Decimal("0")

# Unseen mechanical condition is not free. The reserve is estimated and the
# condition gate still fails closed until an inspection or history check exists.
UNKNOWN_MECHANICAL_EXPECTED_EUR = Decimal("450")
UNKNOWN_MECHANICAL_DOWNSIDE_EUR = Decimal("1500")

# Not a measured selling-channel fee. A conservative friction reserve so the
# max bid does not assume a costless exit.
SELLING_FRICTION_RATE = Decimal("0.08")
SELLING_FRICTION_FLOOR_EUR = Decimal("350")

LIQUIDITY_QUICK_SALE_HAIRCUT = {
    "DEEP": Decimal("0.05"),
    "ADEQUATE": Decimal("0.08"),
    "THIN": Decimal("0.15"),
    "ILLIQUID": Decimal("0.25"),
    "UNKNOWN": Decimal("0.25"),
}

LIQUIDITY_RANK_FACTOR = {
    "DEEP": Decimal("1.00"),
    "ADEQUATE": Decimal("0.85"),
    "THIN": Decimal("0.50"),
    "ILLIQUID": Decimal("0"),
    "UNKNOWN": Decimal("0"),
}

# Mileage rollback beyond this gap between a later and an earlier reading.
MILEAGE_ROLLBACK_TOLERANCE_KM = 50

# Certification is off. Shadow candidates are not purchasing instructions.
CERTIFIED_RECOMMENDATIONS_ENABLED = False
