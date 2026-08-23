"""Query quality for eBay discovery. Accessories must not crowd the feed."""

from __future__ import annotations

import re
from decimal import Decimal

ACCESSORY_RE = re.compile(
    r"\b(case|cover|screen protector|tempered glass|charger|cable|parts only|"
    r"for parts|empty box|box only|hood(?:\s+only)?|lens cap|body cap|filter(?:\s+only)?|"
    r"bag(?:\s+only)?|strap only|cooling block|waterblock|laptop gpu|mobile gpu|"
    r"replica|not genuine)\b",
    re.I,
)

VARIANT_TRAPS = (
    (re.compile(r"\bgm\b(?!\s*ii)", re.I), re.compile(r"\bgm\s*ii\b", re.I)),
)

MIN_PRICE = Decimal("80")
MAX_PRICE = Decimal("2500")


def reject_title(query: str, title: str) -> str | None:
    q = (query or "").lower()
    t = (title or "").lower()
    if ACCESSORY_RE.search(t) and not ACCESSORY_RE.search(q):
        return "accessory"
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
    if "4070" in q and "ti" not in q and re.search(r"4070\s*ti", t):
        return "4070_ti_mismatch"
    if "ps5" in q or "playstation 5" in q:
        if "digital" in t and "digital" not in q:
            return "ps5_digital_mismatch"
    if re.search(r"\b(\d+)\s?gb\b", q) and re.search(r"\b(\d+)\s?gb\b", t):
        want = re.search(r"\b(\d+)\s?gb\b", q)
        got = re.search(r"\b(\d+)\s?gb\b", t)
        if want and got and want.group(1) != got.group(1) and int(got.group(1)) < 64:
            return "storage_mismatch"
    return None


def browse_filter(*, min_price: Decimal = MIN_PRICE, max_price: Decimal = MAX_PRICE) -> str:
    return f"price:[{min_price}..{max_price}]"
