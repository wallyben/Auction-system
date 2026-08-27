"""Comparable matching. Reject accessories, wrong generation, bundles, and mixed grades."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from app.catalogue.store import lookup_catalogue

_REJECT = (
    (re.compile(
        r"\b(battery only|charger only|strap|hood only|body cap|lens cap only|case|cover|"
        r"screen protector|empty box|boite|stand|skin|decal|sticker|faceplate|foam pad|"
        r"power socket|repair part|cooling block|dualsense|manette)\b",
        re.I,
    ), "accessory"),
    (re.compile(r"\b(for parts|spares|broken|faulty|not working)\b", re.I), "broken"),
    (re.compile(r"\b(bundle|kit \+|kit de lentes|with lens|plus extras|job lot)\b", re.I), "bundle"),
    (re.compile(r"\b(psa|bgs|cgc)\s*\d+\b", re.I), "graded"),
    (re.compile(r"\b(refurb(?:ished)?|renewed)\b", re.I), "refurbished"),
)


@dataclass(slots=True)
class CompMatch:
    accepted: bool
    identity_similarity: Decimal
    variant_match: bool
    condition_match: Decimal
    accessory_match: Decimal
    reason: str = ""


def reject_reason(subject_title: str, comp_title: str) -> str | None:
    blob = f"{comp_title}"
    subject = subject_title.lower()
    from app.sources.ebay_filters import ACCESSORY_RE

    if ACCESSORY_RE.search(subject):
        return "subject_is_accessory"
    for pattern, code in _REJECT:
        if pattern.search(blob) and not pattern.search(subject):
            return code
    subj_sku = lookup_catalogue(subject_title)
    comp_sku = lookup_catalogue(comp_title)
    if subj_sku and not comp_sku and "gm ii" in comp_title.lower() and "gm ii" not in subject_title.lower():
        return "different_generation"
    if subj_sku and comp_sku and subj_sku.key != comp_sku.key:
        if subj_sku.family == comp_sku.family:
            return "different_generation"
        return "different_sku"
    if re.search(r"\b(\d+)\s?tb\b", subject) and re.search(r"\b(\d+)\s?tb\b", blob.lower()):
        a = re.search(r"\b(\d+)\s?tb\b", subject)
        b = re.search(r"\b(\d+)\s?tb\b", blob.lower())
        if a and b and a.group(1) != b.group(1):
            return "different_storage"
    if "body only" in subject and re.search(r"\bkit\b", blob, re.I):
        return "body_vs_kit"
    return None


def match_comp(
    subject_title: str,
    comp_title: str,
    *,
    condition_score: Decimal = Decimal("0.7"),
    subject_condition: str | None = None,
    comp_condition: str | None = None,
    subject_description: str = "",
    comp_description: str = "",
    subject_condition_id: str | None = None,
    comp_condition_id: str | None = None,
    strict_identity: bool = False,
) -> CompMatch:
    from app.condition.match import condition_match_score
    from app.sold.match import identity_similarity, variant_reject

    variant = variant_reject(subject_title, comp_title)
    if variant:
        return CompMatch(False, Decimal("0.10"), False, condition_score, Decimal("0"), variant)
    reason = reject_reason(subject_title, comp_title)
    if reason:
        return CompMatch(False, Decimal("0.10"), False, condition_score, Decimal("0"), reason)
    if subject_condition is not None or comp_condition is not None or subject_condition_id or comp_condition_id:
        condition_score = condition_match_score(
            subject_condition,
            comp_condition,
            subject_description=subject_description,
            comp_description=comp_description,
            subject_condition_id=subject_condition_id,
            comp_condition_id=comp_condition_id,
        )
        if condition_score <= 0:
            return CompMatch(False, Decimal("0.10"), False, Decimal("0"), Decimal("0"), "condition_mismatch")
    subj_sku = lookup_catalogue(subject_title)
    comp_sku = lookup_catalogue(comp_title)
    similarity = identity_similarity(subject_title, comp_title)
    if subj_sku and comp_sku and subj_sku.key == comp_sku.key:
        return CompMatch(True, max(similarity, Decimal("0.96")), True, condition_score, Decimal("0.90"))
    tokens = set(re.findall(r"[a-z0-9]+", subject_title.lower()))
    other = set(re.findall(r"[a-z0-9]+", comp_title.lower()))
    if not tokens or not other:
        return CompMatch(False, Decimal("0"), False, condition_score, Decimal("0"), "empty")
    overlap = Decimal(len(tokens & other)) / Decimal(len(tokens | other))
    score = max(overlap, similarity)
    if strict_identity:
        same_key = bool(subj_sku and comp_sku and subj_sku.key == comp_sku.key)
        accepted = same_key or score >= Decimal("0.85")
        return CompMatch(
            accepted,
            score,
            same_key,
            condition_score,
            Decimal("0.90") if same_key else Decimal("0.20"),
            "" if accepted else "strict_identity_mismatch",
        )
    accepted = score >= Decimal("0.35")
    return CompMatch(
        accepted,
        score,
        bool(subj_sku and comp_sku and subj_sku.key == comp_sku.key),
        condition_score,
        Decimal("0.50"),
        "" if accepted else "weak_overlap",
    )
