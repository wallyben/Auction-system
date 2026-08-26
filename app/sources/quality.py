"""Source quality is more than LIVE. Technical ≠ commercially buyable."""

from __future__ import annotations

from typing import Any

from app.core.config import settings


def describe_source(source_id: str, *, technical_status: str, records: int = 0) -> dict[str, Any]:
    ebay_env = settings.ebay_api_env
    table = {
        "ebay_browse": {
            "TECHNICAL_STATUS": technical_status,
            "COMMERCIAL_DATA_QUALITY": (
                "LOW"
                if ebay_env == "sandbox"
                else ("MEDIUM" if technical_status == "LIVE" else "UNKNOWN")
            ),
            "ACQUISITION_OR_VALUATION_ROLE": "ACQUISITION",
            "REAL_MONEY_ELIGIBLE": ebay_env == "production" and technical_status == "LIVE",
            "SOLD_EVIDENCE": False,
            "note": (
                "Sandbox dummy inventory. Not real-money eligible."
                if ebay_env == "sandbox"
                else "Production Browse is active asking prices, not realised sales."
            ),
        },
        "scryfall": {
            "TECHNICAL_STATUS": technical_status,
            "COMMERCIAL_DATA_QUALITY": "LOW",
            "ACQUISITION_OR_VALUATION_ROLE": "VALUATION",
            "REAL_MONEY_ELIGIBLE": False,
            "SOLD_EVIDENCE": False,
            "note": "Cardmarket EUR guide via official Scryfall JSON. Dealer/market, not Irish realised.",
        },
        "reverb": {
            "TECHNICAL_STATUS": technical_status,
            "COMMERCIAL_DATA_QUALITY": "UNKNOWN",
            "ACQUISITION_OR_VALUATION_ROLE": "ACQUISITION",
            "REAL_MONEY_ELIGIBLE": technical_status == "LIVE",
            "SOLD_EVIDENCE": False,
            "note": "Official API. Asking prices unless a sold endpoint is separately proven.",
        },
        "ecb_fx": {
            "TECHNICAL_STATUS": technical_status,
            "COMMERCIAL_DATA_QUALITY": "HIGH",
            "ACQUISITION_OR_VALUATION_ROLE": "REFERENCE",
            "REAL_MONEY_ELIGIBLE": False,
            "SOLD_EVIDENCE": False,
            "note": "Official ECB eurofxref. FX only.",
        },
        "csv_import": {
            "TECHNICAL_STATUS": "LIVE",
            "COMMERCIAL_DATA_QUALITY": "HIGH" if records else "UNKNOWN",
            "ACQUISITION_OR_VALUATION_ROLE": "VALUATION",
            "REAL_MONEY_ELIGIBLE": False,
            "SOLD_EVIDENCE": True,
            "note": "Owner-supplied realised rows. Empty until imported.",
        },
        "manual": {
            "TECHNICAL_STATUS": "LIVE",
            "COMMERCIAL_DATA_QUALITY": "UNKNOWN",
            "ACQUISITION_OR_VALUATION_ROLE": "ACQUISITION",
            "REAL_MONEY_ELIGIBLE": False,
            "SOLD_EVIDENCE": False,
            "note": "Owner-typed asking scenario. Not a live marketplace.",
        },
        "rss_generic": {
            "TECHNICAL_STATUS": technical_status,
            "COMMERCIAL_DATA_QUALITY": "UNKNOWN",
            "ACQUISITION_OR_VALUATION_ROLE": "ACQUISITION",
            "REAL_MONEY_ELIGIBLE": False,
            "SOLD_EVIDENCE": False,
            "note": "Disabled until RSS_URLS is configured.",
        },
    }
    return table.get(
        source_id,
        {
            "TECHNICAL_STATUS": technical_status,
            "COMMERCIAL_DATA_QUALITY": "UNKNOWN",
            "ACQUISITION_OR_VALUATION_ROLE": "OTHER",
            "REAL_MONEY_ELIGIBLE": False,
            "SOLD_EVIDENCE": False,
        },
    )
