"""Camera MARKET_REFERENCE / SANITY_CHECK. Not a sold-ticket substitute.

CameraWorth has no public licensed API (UK vintage auction hammers).
MPB Used Camera Gear Price Index has no public licensed API. Do not scrape either.

Plausibility bands below are CONFIGURED_ASSUMPTION sanity ranges for popular
digital bodies. They never become expected sale, max buy, or realised comps.
If ARIE's accepted-sold median is wildly outside the band, flag VALUATION_ANOMALY
and block BUY_READY until reviewed.
"""

from __future__ import annotations

from decimal import Decimal

from app.sold.cameras import CAMERA_BODIES, CameraBody, camera_from_identity

SANITY_BANDS_EUR: dict[str, tuple[int, int]] = {
    body.canonical_id: (body.sanity_low_eur, body.sanity_high_eur) for body in CAMERA_BODIES
}


def check_anomaly(
    body: CameraBody | None,
    median_eur: Decimal | None,
    *,
    factor: Decimal = Decimal("2.5"),
) -> dict[str, object]:
    if body is None or median_eur is None or median_eur <= 0:
        return {"anomaly": False, "reason": "", "band": None, "median": str(median_eur or 0)}
    low, high = SANITY_BANDS_EUR.get(body.canonical_id, (0, 0))
    if not low or not high:
        return {"anomaly": False, "reason": "no_sanity_band", "band": None, "median": str(median_eur)}
    too_low = median_eur < (Decimal(low) * Decimal("0.55"))
    too_high = median_eur > Decimal(high) * factor
    if too_low or too_high:
        return {
            "anomaly": True,
            "reason": "VALUATION_ANOMALY",
            "band": {"low_eur": low, "high_eur": high, "source": "CONFIGURED_ASSUMPTION_SANITY_BAND"},
            "median": str(median_eur),
            "note": "Accepted-sold median is far from the documented plausibility band. BUY_READY blocked.",
        }
    return {
        "anomaly": False,
        "reason": "",
        "band": {"low_eur": low, "high_eur": high, "source": "CONFIGURED_ASSUMPTION_SANITY_BAND"},
        "median": str(median_eur),
    }


def reference_for_title(title: str) -> CameraBody | None:
    return camera_from_identity(brand=None, model=None, title=title)
