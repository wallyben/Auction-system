"""Query quality for eBay discovery. Accessories must not crowd the feed."""

from __future__ import annotations

import re
from decimal import Decimal

ACCESSORY_RE = re.compile(
    r"\b("
    r"case|cover|screen protector|tempered glass|charger|cable|cables?|"
    r"parts only|for parts|empty box|box only|boite|boîte|"
    r"hood only|lens hood|lens cap|body cap|filter(?:\s+only)?|"
    r"bag(?:\s+only)?|strap only|cooling block|waterblock|"
    r"laptop gpu|mobile gpu|replica|not genuine|"
    r"stand\b|skin\b|decal|sticker|faceplates?|"
    r"foam pad|insulation pad|power socket|dkn\d*|"
    r"repair part|replacement repair|replacement part|moving barrel|"
    r"hall effect stick|drift (?:fix|reparatur)|"
    r"rechargement|charging station|controller stick|"
    r"display model|dummy|housing only|bezel|button set|"
    r"barrel|riparazione|reparaturteil|"
    r"silhouette cut|protective film"
    r")\b",
    re.I,
)

KIT_RE = re.compile(r"\b(kit de lentes|lens kit|bundle|lot of|job lot|\+\s*lens)\b", re.I)

REPAIR_RE = re.compile(
    r"\b(for parts|spares or repair|not working|doesn't work|does not work|"
    r"faulty|broken shutter|cracked sensor|no power|as is repair|"
    r"riparazione|zur reparatur|pour pièces)\b",
    re.I,
)

MIN_PRICE = Decimal("80")
MAX_PRICE = Decimal("2500")

MARKET_CURRENCY = {
    "EBAY_IE": "EUR",
    "EBAY_DE": "EUR",
    "EBAY_FR": "EUR",
    "EBAY_IT": "EUR",
    "EBAY_ES": "EUR",
    "EBAY_NL": "EUR",
    "EBAY_GB": "GBP",
    "EBAY_UK": "GBP",
    "EBAY_US": "USD",
}

# eBay Browse category IDs (global catalogue). Used to keep accessories out of parent searches.
_QUERY_CATEGORIES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"24-70|70-200|16-35|rf\s*\d|gm\s*ii|\blens\b", re.I), "3323"),
    (re.compile(r"a7\s*|a7iv|a7c|ilce|camera body", re.I), "31388"),
    (re.compile(r"macbook", re.I), "11116"),
    (re.compile(r"iphone", re.I), "9355"),
    (re.compile(r"playstation|ps5", re.I), "139971"),
    (re.compile(r"rtx\s*\d|gtx\s*\d|radeon", re.I), "27386"),
    (re.compile(r"ddj|cdj|djm|xone", re.I), "58058"),
    (re.compile(r"sm7b|microphone", re.I), "15196"),
)

_QUERY_BANDS: tuple[tuple[re.Pattern[str], Decimal, Decimal], ...] = (
    (re.compile(r"24-70|70-200|16-35|rf\s*50|gm\s*ii", re.I), Decimal("700"), Decimal("2800")),
    (re.compile(r"a7\s*iv|a7iv|a7c", re.I), Decimal("700"), Decimal("2500")),
    (re.compile(r"macbook", re.I), Decimal("500"), Decimal("2800")),
    (re.compile(r"iphone", re.I), Decimal("220"), Decimal("1400")),
    (re.compile(r"playstation|ps5", re.I), Decimal("220"), Decimal("900")),
    (re.compile(r"rtx\s*40", re.I), Decimal("300"), Decimal("1800")),
    (re.compile(r"ddj|cdj|djm", re.I), Decimal("400"), Decimal("2200")),
    (re.compile(r"sm7b", re.I), Decimal("180"), Decimal("550")),
)

# Exclude FOR_PARTS_OR_NOT_WORKING unless the query is explicitly parts.
_DEFAULT_CONDITIONS = (
    "NEW",
    "LIKE_NEW",
    "NEW_OTHER",
    "CERTIFIED_REFURBISHED",
    "EXCELLENT_REFURBISHED",
    "VERY_GOOD_REFURBISHED",
    "GOOD_REFURBISHED",
    "SELLER_REFURBISHED",
    "USED",
)
_BUYING_OPTIONS = ("FIXED_PRICE", "BEST_OFFER", "AUCTION")


def price_band_for_query(query: str, *, default_min: Decimal = MIN_PRICE, default_max: Decimal = MAX_PRICE) -> tuple[Decimal, Decimal]:
    text = query or ""
    for pattern, low, high in _QUERY_BANDS:
        if pattern.search(text):
            return low, high
    return default_min, default_max


def category_id_for_query(query: str) -> str | None:
    text = query or ""
    for pattern, category_id in _QUERY_CATEGORIES:
        if pattern.search(text):
            return category_id
    return None


def marketplace_currency(marketplace: str) -> str:
    return MARKET_CURRENCY.get((marketplace or "").upper(), "EUR")


def reject_title(query: str, title: str) -> str | None:
    q = (query or "").lower()
    t = (title or "").lower()
    if ACCESSORY_RE.search(t) and not ACCESSORY_RE.search(q):
        return "accessory"
    if KIT_RE.search(t) and not KIT_RE.search(q):
        return "bundle_or_kit"
    if REPAIR_RE.search(t) and not REPAIR_RE.search(q):
        return "repair_or_parts"
    if "gm ii" in q or "gm2" in q:
        if re.search(r"\bgm\b", t) and "gm ii" not in t and "gm2" not in t:
            return "wrong_generation_gm"
    if "gm ii" not in q and "gm2" not in q and "24-70" in q and "gm" in q:
        if "gm ii" in t or "gm2" in t:
            return "wrong_generation_gm_ii"
    if "4080" in q and "super" not in q and "super" in t:
        return "4080_super_mismatch"
    if "4080 super" in q and "super" not in t:
        return "not_super"
    if "4070" in q and "super" not in q and "super" in t:
        return "4070_super_mismatch"
    if "4070" in q and "ti" not in q and re.search(r"4070\s*ti", t):
        return "4070_ti_mismatch"
    if re.search(r"rtx\s*40\d0", q) and re.search(
        r"\b(laptop|mobile|max-q|omen\s*40l|desktop pc|pc omen|gaming pc|prebuilt|whole pc)\b", t
    ):
        return "not_desktop_gpu"
    if "ps5" in q or "playstation 5" in q:
        if "digital" in t and "digital" not in q:
            return "ps5_digital_mismatch"
        if "pro" not in q and re.search(r"ps5\s*pro|playstation\s*5\s*pro", t):
            return "ps5_pro_mismatch"
        if re.search(r"\b(controller|manette|dualsense|faceplate|pad)\b", t) and "console" not in t:
            return "ps5_accessory"
    if re.search(r"a7\s*iv|a7iv|ilce-7m4", q) and "a7r" not in q:
        if re.search(r"a7r\s*iv|a7riv|ilce-7rm4", t):
            return "wrong_generation_a7r"
        if re.search(r"a7\s*iii|a7iii|ilce-7m3", t) and "a7 iv" not in t and "a7iv" not in t.replace(" ", ""):
            return "wrong_generation_a7"
        if re.search(r"\b(lens|obiettivo|objectif|objektiv)\b", t) and not re.search(
            r"\b(body|boitier|gehäuse|ilce-7m4|a7\s*iv|a7iv)\b", t
        ):
            return "lens_when_searching_body"
    if re.search(r"24-70|70-200|16-35|rf\s*\d", q) and re.search(r"\b(body only|boitier seul)\b", t) and "lens" not in t:
        return "body_when_searching_lens"
    iphone_q = re.search(r"iphone\s*(\d+)", q)
    iphone_t = re.search(r"iphone\s*(\d+)", t)
    if iphone_q and iphone_t and iphone_q.group(1) != iphone_t.group(1):
        return "wrong_iphone_generation"
    if "iphone" in q and "pro max" in t and "pro max" not in q:
        return "iphone_pro_max_mismatch"
    if "iphone" in q and re.search(r"\bpro\b", q) and "pro max" not in q:
        if re.search(r"\biphone\s*\d+\s*$", t) or (re.search(r"iphone\s*\d+(?!\s*pro)", t) and "pro" not in t):
            pass
    storages = re.findall(r"(\d+)\s?gb", t)
    unique_phone_storage = {n for n in storages if 32 <= int(n) <= 1024}
    if "iphone" in q and len(unique_phone_storage) >= 3:
        return "multi_variant_listing"
    if re.search(r"\b(\d+)\s?gb\b", q) and re.search(r"\b(\d+)\s?gb\b", t):
        want = re.search(r"\b(\d+)\s?gb\b", q)
        got = re.search(r"\b(\d+)\s?gb\b", t)
        if want and got and want.group(1) != got.group(1):
            want_n, got_n = int(want.group(1)), int(got.group(1))
            if max(want_n, got_n) <= 1024 and want_n != got_n:
                if "iphone" in q or "macbook" in q or got_n < 64:
                    return "storage_mismatch"
    return None


def reject_listing_fields(
    query: str,
    *,
    title: str,
    currency: str | None,
    marketplace: str,
    asking_price: Decimal | None,
    min_price: Decimal,
    max_price: Decimal,
    category_id: str | None = None,
    condition_id: str | None = None,
) -> str | None:
    reason = reject_title(query, title)
    if reason:
        return reason
    expected = marketplace_currency(marketplace)
    if currency and currency.upper() != expected:
        return "currency_mismatch"
    if asking_price is not None and (asking_price < min_price or asking_price > max_price):
        return "price_band"
    if condition_id and str(condition_id) == "7000" and "parts" not in (query or "").lower():
        return "for_parts_condition"
    # Cell-phone accessory leaf under an iPhone search.
    if category_id in {"20349", "9394", "58540"} and "iphone" in (query or "").lower():
        return "accessory_category"
    return None


def browse_filter(
    *,
    min_price: Decimal = MIN_PRICE,
    max_price: Decimal = MAX_PRICE,
    currency: str = "EUR",
    include_parts: bool = False,
) -> str:
    conditions = list(_DEFAULT_CONDITIONS)
    if include_parts:
        conditions.append("FOR_PARTS_OR_NOT_WORKING")
    cond = ",".join(conditions)
    buying = ",".join(_BUYING_OPTIONS)
    return (
        f"price:[{min_price}..{max_price}],priceCurrency:{currency},"
        f"conditions:{{{cond}}},buyingOptions:{{{buying}}}"
    )
