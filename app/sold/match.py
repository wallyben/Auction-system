"""Exact-variant matching for realised comps. Weak overlap is not enough."""

from __future__ import annotations

import re
from decimal import Decimal

from app.identity.resolvers import identify_with_resolvers
from app.models.enums import IdentityLevel
from app.sources.ebay_filters import ACCESSORY_RE, reject_title


def variant_reject(subject_title: str, comp_title: str) -> str | None:
    """Return a reject reason when the sold item is the wrong SKU/variant."""
    subject = subject_title or ""
    other = comp_title or ""
    accessory = reject_title(subject, other)
    if accessory in {
        "accessory",
        "iphone_pro_max_mismatch",
        "4070_super_mismatch",
        "4080_super_mismatch",
        "ps5_pro_mismatch",
        "wrong_iphone_generation",
        "storage_mismatch",
        "wrong_generation_gm",
        "wrong_generation_gm_ii",
        "not_desktop_gpu",
        "lens_when_searching_body",
        "bundle_or_kit",
        "repair_or_parts",
        "ps5_accessory",
        "4070_ti_mismatch",
    }:
        return accessory
    if ACCESSORY_RE.search(other) and not ACCESSORY_RE.search(subject):
        return "accessory"
    st, ot = subject.lower(), other.lower()
    if "pro max" in ot and "pro max" not in st and "iphone" in st:
        return "iphone_pro_max_mismatch"
    if re.search(r"iphone\s*(\d+)", st) and re.search(r"iphone\s*(\d+)", ot):
        if re.search(r"iphone\s*(\d+)", st).group(1) != re.search(r"iphone\s*(\d+)", ot).group(1):
            return "wrong_iphone_generation"
    subj_gb = re.search(r"\b(128|256|512|1024|1)\s*(gb|tb)\b", st)
    comp_gb = re.search(r"\b(128|256|512|1024|1)\s*(gb|tb)\b", ot)
    if "iphone" in st and subj_gb and comp_gb and subj_gb.group(0).replace(" ", "") != comp_gb.group(0).replace(" ", ""):
        return "storage_mismatch"
    subj_chip = re.search(r"\bm([1-4])(?:\s*(pro|max|ultra))?\b", st)
    comp_chip = re.search(r"\bm([1-4])(?:\s*(pro|max|ultra))?\b", ot)
    if "macbook" in st and subj_chip and comp_chip:
        if subj_chip.group(1) != comp_chip.group(1) or (subj_chip.group(2) or "") != (comp_chip.group(2) or ""):
            return "mac_chip_mismatch"
    subj_ram = re.search(r"\b(8|16|18|24|32|36|48|64)\s*/\s*(256|512|1024|1)\b", st)
    comp_ram = re.search(r"\b(8|16|18|24|32|36|48|64)\s*/\s*(256|512|1024|1)\b", ot)
    if "macbook" in st and subj_ram and comp_ram and subj_ram.group(0) != comp_ram.group(0):
        return "mac_memory_mismatch"
    if re.search(r"\b(13|14|15|16)\b", st) and "macbook" in st and "macbook" in ot:
        subj_size = re.search(r"\b(13|14|15|16)\b", st)
        comp_size = re.search(r"\b(13|14|15|16)\b", ot)
        if subj_size and comp_size and subj_size.group(1) != comp_size.group(1):
            return "mac_size_mismatch"
    if "super" in ot and "super" not in st and re.search(r"40\d0", st):
        return "gpu_super_mismatch"
    if re.search(r"4070\s*ti", ot) and "ti" not in st and "4070" in st:
        return "4070_ti_mismatch"
    if re.search(r"\b(laptop|mobile|max-q)\b", ot) and re.search(r"rtx\s*40", st):
        return "not_desktop_gpu"
    if re.search(r"\b(prebuilt|gaming pc|desktop pc|custom pc|tower)\b", ot) and re.search(r"rtx\s*40", st):
        return "gpu_in_desktop"
    if "gm ii" in ot and "gm ii" not in st and "gm2" not in st and re.search(r"24-70|70-200|16-35", st):
        return "wrong_generation_gm_ii"
    if "gm ii" in st and re.search(r"\bgm\b", ot) and "gm ii" not in ot and "gm2" not in ot:
        return "wrong_generation_gm"
    subj_fl = re.search(r"(16-35|24-70|70-200)", st)
    comp_fl = re.search(r"(16-35|24-70|70-200)", ot)
    if subj_fl and comp_fl and subj_fl.group(1) != comp_fl.group(1):
        return "wrong_focal_length"
    subj = identify_with_resolvers(title=subject)
    comp = identify_with_resolvers(title=other)
    if subj.canonical_key and comp.canonical_key and subj.canonical_key == comp.canonical_key:
        return None
    if subj.level in {IdentityLevel.EXACT, IdentityLevel.VARIANT} and comp.model and subj.model:
        if subj.canonical_key and comp.canonical_key and subj.canonical_key != comp.canonical_key:
            if (subj.family or "") == (comp.family or "") or (subj.category == comp.category):
                return "different_variant"
    return None


def identity_similarity(subject_title: str, comp_title: str) -> Decimal:
    subj = identify_with_resolvers(title=subject_title)
    comp = identify_with_resolvers(title=comp_title)
    if subj.canonical_key and comp.canonical_key and subj.canonical_key == comp.canonical_key:
        return Decimal("0.96")
    tokens = set(re.findall(r"[a-z0-9]+", (subject_title or "").lower()))
    other = set(re.findall(r"[a-z0-9]+", (comp_title or "").lower()))
    if not tokens or not other:
        return Decimal("0")
    return Decimal(len(tokens & other)) / Decimal(len(tokens | other))
