"""Category-grade identity resolvers. Generic text parsing is not enough for variants."""

from __future__ import annotations

import re
from decimal import Decimal

from app.identity.engine import ProductIdentity, identify_listing as generic_identify
from app.models.enums import IdentityLevel

_GM_II = re.compile(r"\b(?:24-70|24\s*-\s*70).{0,20}\bgm\s*ii\b|\bgm\s*ii\b.{0,20}24-70", re.I)
_GM1 = re.compile(r"\b(?:24-70|70-200|16-35).{0,12}\bgm\b(?!\s*ii)", re.I)
_SUPER = re.compile(r"\b(rtx\s*)?(40\d0|30\d0|50\d0)\s*super\b", re.I)
_GPU = re.compile(r"\b(rtx|gtx|rx)\s*(\d{3,4})\s*(ti|super|xt|xtx)?\b", re.I)
_A7 = re.compile(r"\ba7\s*(r|s|c)?\s*(iv|iii|ii|v|i)?\b", re.I)
_RF_LENS = re.compile(r"\brf\s*(\d{2,3})(?:\s*-\s*(\d{2,3}))?(?:\s*mm)?\s*(?:f/?\s*([\d.]+))?", re.I)
_MACBOOK = re.compile(
    r"\bmacbook\s*(air|pro)?\s*(13|14|15|16)?\s*(?:inch)?\s*(m[1-4](?:\s*pro|\s*max|\s*ultra)?|\bi[5-9]|m-series)?",
    re.I,
)
_IPHONE = re.compile(r"\biphone\s*(\d{1,2}|x[sr]?)\s*(pro(?:\s*max)?|plus|mini|air)?\s*(\d+\s*gb|\d+\s*tb)?", re.I)
_PS = re.compile(r"\b(ps5|playstation\s*5)(?:\s*(slim|pro|digital|disc))?", re.I)
_SWITCH = re.compile(r"\b(switch)\s*(oled|lite|2)?\b", re.I)
_XBOX = re.compile(r"\bxbox\s*series\s*([xs])\b", re.I)
_DDJ = re.compile(r"\b(ddj[-\s]?\w+|cdj[-\s]?\d{3,4}|xone\s*\d+|djm[-\s]?\d+)\b", re.I)
_MIC = re.compile(r"\b(sm7b|sm58|sm57|nt1|at2020|mv7)\b", re.I)
_CARD = re.compile(r"\b(foil|extended|borderless|showcase|serialized)\b", re.I)


def _finish(base: ProductIdentity, **updates: object) -> ProductIdentity:
    data = {slot: getattr(base, slot) for slot in base.__slots__}
    data.update(updates)
    return ProductIdentity(**data)  # type: ignore[arg-type]


def resolve_camera(base: ProductIdentity, text: str) -> ProductIdentity:
    match = _A7.search(text)
    if match:
        variant = "".join(part or "" for part in match.groups()).upper()
        model = re.sub(r"\s+", " ", match.group(0)).strip()
        level = IdentityLevel.EXACT
        conf = max(base.confidence, Decimal("0.82"))
        return _finish(
            base,
            brand=base.brand or "Sony",
            family="Alpha",
            model=model,
            variant=variant or base.variant,
            category="cameras",
            level=level,
            confidence=min(conf, Decimal("0.95")),
            canonical_key=f"sony|{model.lower()}|{base.storage or ''}",
        )
    return _finish(base, category=base.category or "cameras")


def resolve_lens(base: ProductIdentity, text: str) -> ProductIdentity:
    if _GM_II.search(text):
        return _finish(
            base,
            brand=base.brand or "Sony",
            family="GM",
            model="FE 24-70mm GM II",
            variant="GM II",
            category="lenses",
            level=IdentityLevel.EXACT,
            confidence=max(base.confidence, Decimal("0.90")),
            canonical_key="sony|fe-24-70-gm-ii",
        )
    if _GM1.search(text) and "gm ii" not in text:
        fl = re.search(r"(16-35|24-70|70-200)", text)
        focal = fl.group(1) if fl else "24-70"
        return _finish(
            base,
            brand=base.brand or "Sony",
            family="GM",
            model=f"FE {focal} GM",
            variant="GM I",
            category="lenses",
            level=IdentityLevel.EXACT,
            confidence=max(base.confidence, Decimal("0.88")),
            canonical_key=f"sony|fe-{focal}-gm",
        )
    rf = _RF_LENS.search(text)
    if rf:
        model = re.sub(r"\s+", " ", rf.group(0)).strip()
        return _finish(
            base,
            brand=base.brand or "Canon",
            model=model,
            category="lenses",
            level=IdentityLevel.VARIANT,
            confidence=max(base.confidence, Decimal("0.80")),
        )
    return _finish(base, category=base.category or "lenses")


def resolve_apple(base: ProductIdentity, text: str) -> ProductIdentity:
    mac = _MACBOOK.search(text)
    if mac:
        size = mac.group(2) or ""
        chip = (mac.group(3) or "").strip()
        family = mac.group(1) or "pro"
        model = f"MacBook {family.title()} {size}".strip()
        if not chip:
            return _finish(
                base,
                brand="Apple",
                family="MacBook",
                model=model,
                variant=base.storage,
                category="computing",
                level=IdentityLevel.FAMILY,
                confidence=min(max(base.confidence, Decimal("0.55")), Decimal("0.70")),
                missing=list(base.missing) + ["generation/chip"],
                canonical_key=f"apple|{model.lower()}|{chip.lower()}|{base.storage or ''}",
            )
        return _finish(
            base,
            brand="Apple",
            family="MacBook",
            model=f"{model} {chip}",
            variant=base.storage,
            category="computing",
            level=IdentityLevel.EXACT if base.storage else IdentityLevel.VARIANT,
            confidence=max(base.confidence, Decimal("0.86" if base.storage else "0.78")),
            canonical_key=f"apple|{model.lower()}|{chip.lower()}|{base.storage or ''}",
        )
    iphone = _IPHONE.search(text)
    if iphone:
        model = re.sub(r"\s+", " ", iphone.group(0)).strip()
        return _finish(
            base,
            brand="Apple",
            family="iPhone",
            model=model,
            category="consumer_electronics",
            level=IdentityLevel.VARIANT if iphone.group(3) else IdentityLevel.FAMILY,
            confidence=max(base.confidence, Decimal("0.80")),
        )
    return _finish(base, brand=base.brand or "Apple", category=base.category or "computing")


def resolve_gpu(base: ProductIdentity, text: str) -> ProductIdentity:
    if _SUPER.search(text):
        num = re.search(r"40\d0|30\d0|50\d0", text, re.I)
        model = f"RTX {num.group(0)} SUPER" if num else "RTX SUPER"
        return _finish(
            base,
            family="GeForce",
            model=model,
            variant="SUPER",
            category="gpu",
            level=IdentityLevel.EXACT,
            confidence=max(base.confidence, Decimal("0.90")),
            canonical_key=f"nvidia|{model.lower()}",
        )
    gpu = _GPU.search(text)
    if gpu:
        model = re.sub(r"\s+", " ", gpu.group(0)).upper()
        if "super" in text and "super" not in model.lower():
            return _finish(base, model=model, category="gpu", level=IdentityLevel.FAMILY, confidence=Decimal("0.55"))
        return _finish(
            base,
            model=model,
            category="gpu",
            level=IdentityLevel.EXACT,
            confidence=max(base.confidence, Decimal("0.84")),
            canonical_key=f"gpu|{model.lower()}",
        )
    return _finish(base, category=base.category or "gpu")


def resolve_console(base: ProductIdentity, text: str) -> ProductIdentity:
    ps = _PS.search(text)
    if ps:
        edition = (ps.group(2) or "disc").lower()
        digital = "digital" in text or edition == "digital"
        return _finish(
            base,
            brand="Sony",
            family="PlayStation",
            model=f"PS5 {edition}",
            variant="digital" if digital else "disc",
            category="gaming",
            level=IdentityLevel.VARIANT,
            confidence=max(base.confidence, Decimal("0.82")),
            canonical_key=f"sony|ps5|{edition}",
        )
    sw = _SWITCH.search(text)
    if sw:
        variant = (sw.group(2) or "standard").lower()
        return _finish(
            base,
            brand="Nintendo",
            model=f"Switch {variant}",
            category="gaming",
            level=IdentityLevel.VARIANT,
            confidence=max(base.confidence, Decimal("0.80")),
        )
    xb = _XBOX.search(text)
    if xb:
        return _finish(
            base,
            brand="Microsoft",
            model=f"Xbox Series {xb.group(1).upper()}",
            category="gaming",
            level=IdentityLevel.EXACT,
            confidence=max(base.confidence, Decimal("0.84")),
        )
    return _finish(base, category=base.category or "gaming")


def resolve_dj(base: ProductIdentity, text: str) -> ProductIdentity:
    ddj = _DDJ.search(text)
    if ddj:
        model = re.sub(r"\s+", " ", ddj.group(1)).upper()
        return _finish(
            base,
            model=model,
            category="music_dj",
            level=IdentityLevel.EXACT,
            confidence=max(base.confidence, Decimal("0.86")),
            canonical_key=f"dj|{model.lower()}",
        )
    return _finish(base, category=base.category or "music_dj")


def resolve_audio(base: ProductIdentity, text: str) -> ProductIdentity:
    mic = _MIC.search(text)
    if mic:
        return _finish(
            base,
            model=mic.group(1).upper(),
            category="pro_av",
            level=IdentityLevel.EXACT,
            confidence=max(base.confidence, Decimal("0.88")),
        )
    return _finish(base, category=base.category or "pro_av")


def resolve_card(base: ProductIdentity, text: str) -> ProductIdentity:
    foil = bool(re.search(r"\bfoil\b", text, re.I))
    variant = "foil" if foil else (base.variant or "nonfoil")
    return _finish(
        base,
        category="trading_cards",
        variant=variant,
        level=base.level if base.level != IdentityLevel.UNKNOWN else IdentityLevel.FAMILY,
        confidence=min(base.confidence + (Decimal("0.05") if foil else Decimal("0")), Decimal("0.92")),
    )


_DISPATCH = (
    (re.compile(r"\b(lens|gm|rf\s*\d|24-70|70-200|16-35)\b", re.I), resolve_lens),
    (re.compile(r"\b(a7|a9|r5|r6|z8|z9|x-t|gfx|camera body)\b", re.I), resolve_camera),
    (re.compile(r"\b(macbook|iphone|ipad|imac)\b", re.I), resolve_apple),
    (re.compile(r"\b(rtx|gtx|radeon|rx\s*\d)\b", re.I), resolve_gpu),
    (re.compile(r"\b(ps5|playstation|switch|xbox)\b", re.I), resolve_console),
    (re.compile(r"\b(ddj|cdj|djm|xone|controller|mixer)\b", re.I), resolve_dj),
    (re.compile(r"\b(sm7|sm58|microphone|headphones|synthesizer|korg|moog)\b", re.I), resolve_audio),
    (re.compile(r"\b(mtg|magic the gathering|pokemon|yugioh|card)\b", re.I), resolve_card),
)


def identify_with_resolvers(
    *,
    title: str,
    description: str = "",
    brand_hint: str | None = None,
    model_hint: str | None = None,
    gtin: str | None = None,
    mpn: str | None = None,
    category: str | None = None,
) -> ProductIdentity:
    """Generic parse first, then a category plugin upgrades variant exactness."""
    base = generic_identify(
        title=title,
        description=description,
        brand_hint=brand_hint,
        model_hint=model_hint,
        gtin=gtin,
        mpn=mpn,
        category=category,
    )
    blob = f"{title}\n{description}\n{brand_hint or ''}\n{model_hint or ''}".lower()
    from app.sources.ebay_filters import ACCESSORY_RE, KIT_RE

    if ACCESSORY_RE.search(blob) or KIT_RE.search(blob):
        missing = list(base.missing) + ["accessory_or_kit"]
        return _finish(
            base,
            level=IdentityLevel.CATEGORY,
            confidence=min(base.confidence, Decimal("0.35")),
            missing=missing,
            canonical_key=f"accessory|{base.canonical_key}",
        )
    for pattern, resolver in _DISPATCH:
        if pattern.search(blob):
            return resolver(base, blob)
    return base
