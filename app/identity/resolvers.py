"""Category-grade identity resolvers. Generic text parsing is not enough for variants."""

from __future__ import annotations

import re
from decimal import Decimal

from app.identity.engine import ProductIdentity, identify_listing as generic_identify
from app.identity.schemas import parse_camera, parse_gpu, parse_macbook, parse_phone
from app.models.enums import IdentityLevel

GAME_RE = re.compile(
    r"\b("
    r"fifa|ea\s*sports\s*fc|gta|grand theft auto|call of duty|cod\s+\d|"
    r"spider-man|spiderman|horizon forbidden|god of war|game\s+only|"
    r"digital\s+code|voucher\s+code|psn\s+card|"
    r"mario kart|zelda|pokemon violet|pokemon scarlet"
    r")\b",
    re.I,
)

_GM_II = re.compile(
    r"\b(?:16-35|24-70|70-200).{0,28}\bgm\s*ii\b|\bgm\s*ii\b.{0,28}(?:16-35|24-70|70-200)",
    re.I,
)
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
    parsed = parse_camera(text)
    if parsed and parsed.model:
        attrs = {
            "manufacturer": parsed.manufacturer or "",
            "model": parsed.model,
            "generation": parsed.generation or "",
            "body_or_kit": parsed.body_or_kit or "body",
        }
        key = "|".join(parsed.canonical_parts())
        exact = bool(parsed.generation and parsed.model)
        product_class = "camera_body" if (parsed.body_or_kit or "body") == "body" else "camera_kit"
        from app.sold.cameras import camera_from_identity

        catalog = camera_from_identity(brand=parsed.manufacturer, model=parsed.model, title=text)
        key = catalog.canonical_id if catalog else "|".join(parsed.canonical_parts())
        return _finish(
            base,
            brand=parsed.manufacturer or base.brand or "Sony",
            family=parsed.tier or "Alpha",
            model=parsed.model,
            variant=parsed.body_or_kit or "body",
            category="cameras",
            level=IdentityLevel.EXACT if exact and product_class == "camera_body" else IdentityLevel.VARIANT,
            confidence=max(base.confidence, Decimal("0.92") if exact else Decimal("0.84")),
            canonical_key=key or "sony|a7",
            attributes=attrs,
            product_class=product_class,
        )
    if re.search(r"ilce-7m4|a7\s*iv|a7iv", text) and not re.search(r"a7r|ilce-7rm4", text):
        return _finish(
            base,
            brand=base.brand or "Sony",
            family="Alpha",
            model="A7 IV",
            variant="body",
            category="cameras",
            level=IdentityLevel.EXACT,
            confidence=max(base.confidence, Decimal("0.92")),
            canonical_key="sony|a7-iv|body",
            attributes={"manufacturer": "Sony", "model": "A7 IV", "generation": "IV", "body_or_kit": "body"},
            product_class="camera_body",
        )
    if re.search(r"ilce-7m3|a7\s*iii|a7iii", text) and not re.search(r"a7\s*iv|a7iv", text):
        return _finish(
            base,
            brand=base.brand or "Sony",
            family="Alpha",
            model="A7 III",
            variant="body",
            category="cameras",
            level=IdentityLevel.EXACT,
            confidence=max(base.confidence, Decimal("0.90")),
            canonical_key="sony|a7-iii|body",
            product_class="camera_body",
        )
    match = _A7.search(text)
    if match:
        variant = "".join(part or "" for part in match.groups()).upper()
        model = re.sub(r"\s+", " ", match.group(0)).strip()
        return _finish(
            base,
            brand=base.brand or "Sony",
            family="Alpha",
            model=model,
            variant=variant or base.variant,
            category="cameras",
            level=IdentityLevel.EXACT,
            confidence=max(base.confidence, Decimal("0.90")),
            canonical_key=f"sony|{model.lower()}|{base.storage or ''}",
            product_class="camera_body",
        )
    return _finish(base, category=base.category or "cameras")


def resolve_lens(base: ProductIdentity, text: str) -> ProductIdentity:
    if _GM_II.search(text):
        fl = re.search(r"(16-35|24-70|70-200)", text)
        focal = fl.group(1) if fl else "24-70"
        return _finish(
            base,
            brand=base.brand or "Sony",
            family="GM",
            model=f"FE {focal}mm GM II",
            variant="GM II",
            category="lenses",
            level=IdentityLevel.EXACT,
            confidence=max(base.confidence, Decimal("0.92")),
            canonical_key=f"sony|fe-{focal}-gm-ii",
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
    phone = parse_phone(text)
    if phone and phone.model:
        exact = bool(phone.storage and phone.tier)
        return _finish(
            base,
            brand="Apple",
            family="iPhone",
            model=phone.model,
            variant=phone.storage,
            storage=phone.storage or base.storage,
            category="consumer_electronics",
            level=IdentityLevel.EXACT if exact else IdentityLevel.VARIANT,
            confidence=max(base.confidence, Decimal("0.92") if exact else Decimal("0.82")),
            canonical_key="|".join(phone.canonical_parts()),
            missing=list(base.missing) + phone.missing,
            attributes={
                "manufacturer": "Apple",
                "model": phone.model,
                "generation": phone.generation or "",
                "tier": phone.tier or "",
                "storage": phone.storage or "",
                "carrier": phone.carrier or "",
            },
            product_class="primary",
        )
    parsed_mac = parse_macbook(text)
    if parsed_mac and parsed_mac.model:
        exact = bool(parsed_mac.chip and parsed_mac.storage and parsed_mac.size)
        return _finish(
            base,
            brand="Apple",
            family="MacBook",
            model=f"{parsed_mac.model} {parsed_mac.size or ''} {parsed_mac.chip or ''}".strip(),
            variant=" ".join(p for p in [parsed_mac.chip, parsed_mac.ram, parsed_mac.storage] if p),
            storage=parsed_mac.storage or base.storage,
            category="computing",
            level=IdentityLevel.EXACT if exact else IdentityLevel.FAMILY if parsed_mac.missing else IdentityLevel.VARIANT,
            confidence=max(base.confidence, Decimal("0.92") if exact else Decimal("0.70") if parsed_mac.chip else Decimal("0.58")),
            canonical_key="|".join(parsed_mac.canonical_parts()),
            missing=list(base.missing) + parsed_mac.missing,
            attributes={
                "manufacturer": "Apple",
                "model": parsed_mac.model,
                "chip": parsed_mac.chip or "",
                "ram": parsed_mac.ram or "",
                "storage": parsed_mac.storage or "",
                "size": parsed_mac.size or "",
                "family": parsed_mac.tier or "",
            },
            product_class="primary",
        )
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
        ram = re.search(r"\b(8|16|18|24|32|36|48|64|96|128)\s*gb\b", text)
        storage = base.storage
        exact = bool(chip and storage and size)
        return _finish(
            base,
            brand="Apple",
            family="MacBook",
            model=f"{model} {chip}",
            variant=" ".join(part for part in [chip, ram.group(0).upper() if ram else "", storage or ""] if part),
            category="computing",
            level=IdentityLevel.EXACT if exact else IdentityLevel.VARIANT,
            confidence=max(base.confidence, Decimal("0.92") if exact else Decimal("0.80")),
            canonical_key=f"apple|{model.lower()}|{chip.lower()}|{storage or ''}",
        )
    iphone = _IPHONE.search(text)
    if iphone:
        gen = iphone.group(1)
        tier = (iphone.group(2) or "").strip()
        storage = (iphone.group(3) or base.storage or "").replace(" ", "").upper()
        model = f"iPhone {gen} {tier}".strip()
        exact = bool(storage and tier)
        return _finish(
            base,
            brand="Apple",
            family="iPhone",
            model=model,
            variant=storage,
            category="consumer_electronics",
            level=IdentityLevel.EXACT if exact else IdentityLevel.VARIANT,
            confidence=max(base.confidence, Decimal("0.92") if exact else Decimal("0.82")),
            canonical_key=f"apple|{model.lower()}|{storage.lower()}",
        )
    return _finish(base, brand=base.brand or "Apple", category=base.category or "computing")


def resolve_gpu(base: ProductIdentity, text: str) -> ProductIdentity:
    parsed = parse_gpu(text)
    if parsed and parsed.extra.get("form") == "laptop":
        return _finish(
            base,
            family="GeForce",
            model=parsed.model,
            variant="laptop",
            category="gpu",
            level=IdentityLevel.FAMILY,
            confidence=min(max(base.confidence, Decimal("0.40")), Decimal("0.55")),
            canonical_key=f"gpu|{parsed.model.lower()}|laptop",
            product_class="primary",
            attributes={"form": "laptop", "model": parsed.model or ""},
            missing=list(base.missing) + ["desktop_gpu"],
        )
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
            confidence=max(base.confidence, Decimal("0.90")),
            canonical_key=f"gpu|{model.lower()}",
        )
    return _finish(base, category=base.category or "gpu")


def resolve_console(base: ProductIdentity, text: str) -> ProductIdentity:
    if GAME_RE.search(text) and not re.search(r"\b(console|bundle with console)\b", text, re.I):
        return _finish(
            base,
            category="gaming",
            level=IdentityLevel.CATEGORY,
            confidence=min(base.confidence, Decimal("0.30")),
            product_class="game",
            missing=list(base.missing) + ["console_vs_game"],
            canonical_key=f"game|{base.canonical_key}",
        )
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
            level=IdentityLevel.EXACT if ps.group(2) else IdentityLevel.VARIANT,
            confidence=max(base.confidence, Decimal("0.90") if ps.group(2) else Decimal("0.84")),
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
            confidence=max(base.confidence, Decimal("0.90")),
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
            confidence=max(base.confidence, Decimal("0.90")),
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
    (re.compile(r"\b(a7|a9|r5|r6|z8|z9|x-t|gfx|camera body|ilce)\b", re.I), resolve_camera),
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
            product_class="accessory",
            category=base.category or category or "accessory",
        )
    if GAME_RE.search(blob) and re.search(r"\b(ps5|playstation|xbox|switch|console)\b", blob):
        if not re.search(r"\b(console|disc edition|digital edition)\b", blob):
            return _finish(
                base,
                level=IdentityLevel.CATEGORY,
                confidence=min(base.confidence, Decimal("0.30")),
                missing=list(base.missing) + ["console_vs_game"],
                canonical_key=f"game|{base.canonical_key}",
                product_class="game",
                category="gaming",
            )
    for pattern, resolver in _DISPATCH:
        if pattern.search(blob):
            return resolver(base, blob)
    return base
