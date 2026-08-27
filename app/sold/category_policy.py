"""Which realised-comp sources are legitimate per category.

Asking comps cannot certify BUY_READY. Reverb is only a support source for
DJ / pro-audio SKUs, never cameras, phones, GPUs, or consoles.
"""

from __future__ import annotations

# Ordered preference. Insights and owner OAuth populate sold_evidence when entitled.
REALISED_SOURCES = (
    "owner_recorded",
    "ebay_owner_fulfillment",
    "ebay_marketplace_insights",
    "compsniper",
    "irish_panel",
    "owner_trade_floor",
)

CATEGORY_COMP_POLICY: dict[str, dict[str, object]] = {
    "cameras": {
        "realised": REALISED_SOURCES,
        "asking": (),
        "reverb": False,
        "notes": "Cameras require eBay realised / CompSniper completed sales / owner sold. Reverb asking is not a camera market.",
    },
    "lenses": {
        "realised": REALISED_SOURCES,
        "asking": (),
        "reverb": False,
        "notes": "Lenses require eBay realised / owner sold. Do not inherit parent-SKU Reverb asks.",
    },
    "computing": {
        "realised": REALISED_SOURCES,
        "asking": (),
        "reverb": False,
        "notes": "Apple / MacBook: realised eBay and owner sales only.",
    },
    "consumer_electronics": {
        "realised": REALISED_SOURCES,
        "asking": (),
        "reverb": False,
        "notes": "iPhone: realised eBay / owner sales. No Reverb.",
    },
    "gpu": {
        "realised": REALISED_SOURCES,
        "asking": (),
        "reverb": False,
        "notes": "GPU: realised eBay / owner sales only.",
    },
    "gaming": {
        "realised": REALISED_SOURCES,
        "asking": (),
        "reverb": False,
        "notes": "PS5 / consoles: realised eBay / owner sales. No Reverb.",
    },
    "music_dj": {
        "realised": REALISED_SOURCES,
        "asking": ("reverb",),
        "reverb": True,
        "notes": "DJ: realised eBay / owner sold first. Reverb asking is support only, never BUY_READY evidence.",
    },
    "pro_av": {
        "realised": REALISED_SOURCES,
        "asking": ("reverb",),
        "reverb": True,
        "notes": "Pro audio: realised eBay / owner sold first. Reverb asking is support only.",
    },
    "trading_cards": {
        "realised": REALISED_SOURCES,
        "asking": (),
        "reverb": False,
        "notes": "Cards use Scryfall/Cardmarket guides, not Reverb.",
    },
}


def reverb_allowed_for(category: str | None) -> bool:
    if not category:
        return False
    policy = CATEGORY_COMP_POLICY.get(category)
    if not policy:
        return False
    return bool(policy.get("reverb"))
