"""Product-class-first identity firewall.

A listing that *mentions* a camera is not a camera body. Accessory titles
inherit compatibility, never canonical body identity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.sold.cameras import CAMERA_BODIES, camera_from_identity, token_in

CAMERA_BODY = "camera_body"
LENS = "lens"
CAGE = "cage"
BATTERY_GRIP = "battery_grip"
MICROPHONE = "microphone"
ADAPTER = "adapter"
BATTERY = "battery"
CHARGER = "charger"
CASE = "case"
STRAP = "strap"
SCREEN_PROTECTOR = "screen_protector"
MANUAL = "manual"
BOX_ONLY = "box_only"
PARTS = "parts"
OTHER_ACCESSORY = "other_accessory"
KIT = "kit"
UNKNOWN = "unknown"

ACCESSORY_CLASSES = frozenset(
    {
        LENS,
        CAGE,
        BATTERY_GRIP,
        MICROPHONE,
        ADAPTER,
        BATTERY,
        CHARGER,
        CASE,
        STRAP,
        SCREEN_PROTECTOR,
        MANUAL,
        BOX_ONLY,
        PARTS,
        OTHER_ACCESSORY,
        KIT,
    }
)
BODY_IDENTITY_FORBIDDEN = ACCESSORY_CLASSES | {"accessory", "game", "consumable"}

# Structured families. First matching family wins. Not one giant regex.
_FAMILIES: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        BOX_ONLY,
        (
            re.compile(r"\b(empty\s+box|box\s+only|boite\s+vide|boîte\s+vide)\b", re.I),
            re.compile(r"\b(retail\s+box\s+only|original\s+box\s+only)\b", re.I),
        ),
    ),
    (
        MANUAL,
        (
            re.compile(r"\b(instruction\s+manual|user\s+manual|reference\s+manual|manual\s+only|manuel\s+d.utilisation)\b", re.I),
            re.compile(r"\bmanual\s+for\b", re.I),
        ),
    ),
    (
        PARTS,
        (
            re.compile(
                r"\b(motherboard|mainboard|pcb|shutter\s+unit|shutter\s+group|shutter\s+assembly|"
                r"repair\s+part|replacement\s+door|lcd\s+screen\s+replacement|screen\s+replacement|"
                r"replacement\s+lcd|genuine\s+sony\s+spare|image\s+sensor\s+parts|cmos\s+image\s+sensor|"
                r"cmos\s+sensor|sensor\s+parts|for\s+parts|spares\s+or\s+repair|broken\s+shutter|cracked\s+sensor)\b",
                re.I,
            ),
            re.compile(r"\bcg2-\d", re.I),
            re.compile(r"\bcy3-\d", re.I),
        ),
    ),
    (
        CAGE,
        (
            re.compile(r"\b(camera\s+cage|cage\s+kit|video\s+rig|cage\s+for)\b", re.I),
            re.compile(r"\b(smallrig|hersmay|uu-rig|uurig|nifty)\b", re.I),
            re.compile(r"\b(l-?bracket|l\s+bracket|l-?plate|l\s+plate|nato\s+rail|top\s+handle\s+side\s+grip)\b", re.I),
            re.compile(r"\bcage\b", re.I),
        ),
    ),
    (
        BATTERY_GRIP,
        (
            re.compile(r"\b(battery\s+grip|vertical\s+grip|portrait\s+grip)\b", re.I),
            re.compile(r"\bbg-r\d+\b", re.I),
            re.compile(r"\b(vg-c\d|mb-n\d+)\b", re.I),
        ),
    ),
    (
        MICROPHONE,
        (
            re.compile(r"\b(shotgun\s+mic(?:rophone)?|hot\s+shoe\s+mic(?:rophone)?)\b", re.I),
            re.compile(r"\becm-[a-z0-9]+\b", re.I),
            re.compile(r"\bmic(?:rophone)?\s+(?:for|compatible\s+with)\b", re.I),
            re.compile(r"\b(camera\s+mic(?:rophone)?|on-camera\s+mic)\b", re.I),
        ),
    ),
    (
        SCREEN_PROTECTOR,
        (
            re.compile(r"\b(screen\s+protector|tempered\s+glass|lcd\s+protector)\b", re.I),
        ),
    ),
    (
        CHARGER,
        (
            re.compile(r"\b(battery\s+charger|dual\s+charger|bc-qz1|bc-qzl)\b", re.I),
            re.compile(r"\bcharger\s+for\b", re.I),
        ),
    ),
    (
        BATTERY,
        (
            re.compile(r"\b(dummy\s+battery|dummy\s+pack|np-fz100|np-fw50|lp-e6|lp-e6nh)\b", re.I),
            re.compile(r"\b(replacement\s+battery|spare\s+batter(?:y|ies)\s+for)\b", re.I),
            re.compile(r"\bbatter(?:y|ies)\s+for\b", re.I),
        ),
    ),
    (
        ADAPTER,
        (
            re.compile(r"\b(lens\s+adapter|mount\s+adapter|mc-11|mc-21|ftz\s*ii?)\b", re.I),
            re.compile(r"\badapter\s+(?:for|ring)\b", re.I),
        ),
    ),
    (
        STRAP,
        (
            re.compile(r"\b(neck\s+strap|camera\s+strap|wrist\s+strap|strap\s+only)\b", re.I),
            re.compile(r"\bstrap\s+for\b", re.I),
        ),
    ),
    (
        CASE,
        (
            re.compile(r"\b(camera\s+case|leather\s+case|silicone\s+case|ever\s+ready\s+case)\b", re.I),
            re.compile(r"\b(case|cover|housing|pouch)\s+for\b", re.I),
            re.compile(r"\b(protective\s+case|body\s+cover)\b", re.I),
        ),
    ),
    (
        LENS,
        (
            re.compile(r"\b(fe\s+\d{2,3}|rf\s+\d{2,3}|xf\s+\d{2,3}|gm\s*ii?|prime\s+lens|zoom\s+lens)\b", re.I),
            re.compile(r"\b\d{2,3}(?:-\d{2,3})?\s*mm\b", re.I),
        ),
    ),
    (
        KIT,
        (
            re.compile(r"\b(lens\s+kit|kit\s+lens|with\s+(?:kit\s+)?lens|bundle\s+with)\b", re.I),
            re.compile(r"\bkit\b", re.I),
        ),
    ),
    (
        OTHER_ACCESSORY,
        (
            re.compile(r"\b(quick\s+release\s+plate|camera\s+plate|l-?plate)\b", re.I),
            re.compile(r"\b(remote\s+(?:control|shutter)|intervalometer|dummy\s+battery)\b", re.I),
            re.compile(r"\b(hot\s+shoe|flash\s+trigger)\b", re.I),
        ),
    ),
)

_COMPAT_FOR = re.compile(
    r"\b(?:compatible\s+with|fits|passend\s+f[uü]r|pour)\b"
    r"|\bfor\s+(?!sale\b|auction\b)(?=.{0,48}(?:"
    r"canon|sony|nikon|fuji|fujifilm|panasonic|olympus|eos|alpha|"
    r"a7|a9|r5|r6|r8|r10|z5|z6|z7|z8|z9|x-t|ilce|gfx"
    r"))",
    re.I,
)
_BODY_SUBJECT = re.compile(
    r"\b(body\s+only|camera\s+body|mirrorless(?:\s+digital)?\s+camera(?:\s+body)?|"
    r"bo[iî]tier|gehäuse(?:\s+only)?|ilce-|eos\s+r\d|x-t\d)\b",
    re.I,
)
_BODY_ONLY = re.compile(r"\b(body\s+only|bo[iî]tier\s+nu|gehäuse\s+only)\b", re.I)
# Genuine body listings often include spare batteries / original box as extras.
_INCIDENTAL = re.compile(
    r"\b(in\s+original\s+(?:box|case)|with\s+(?:original\s+)?box|"
    r"\d+\s+batter(?:y|ies)|two\s+batter(?:y|ies)|extra\s+batter(?:y|ies)|"
    r"low\s+shutter|shutter\s+count)\b",
    re.I,
)


@dataclass(frozen=True, slots=True)
class ProductClassResult:
    product_class: str
    reason: str
    compatible_camera_ids: tuple[str, ...] = field(default_factory=tuple)


_MARK = re.compile(r"\bmark\s+(i{1,3}|iv|v|vi)\b", re.I)


def _norm_compat_text(text: str) -> str:
    return _MARK.sub(lambda m: m.group(1).lower(), (text or "").lower())


def _needle_in(blob: str, needle: str) -> bool:
    return token_in(blob, needle)


def compatible_cameras(text: str) -> tuple[str, ...]:
    """Camera models mentioned as compatibility, not identity."""
    found: list[str] = []
    blob = _norm_compat_text(text or "")
    ranked = sorted(CAMERA_BODIES, key=lambda b: len(b.model), reverse=True)
    for body in ranked:
        needles = (
            _norm_compat_text(body.model),
            _norm_compat_text(body.mpn),
            *tuple(_norm_compat_text(a) for a in body.aliases),
        )
        if any(_needle_in(blob, needle) for needle in needles):
            if body.canonical_id not in found:
                found.append(body.canonical_id)
    hit = camera_from_identity(brand=None, model=None, title=text)
    if hit is not None and hit.canonical_id not in found:
        found.append(hit.canonical_id)
    # Drop generic models when a more specific generation also matched (R6 vs R6 II).
    keep: list[str] = []
    models = {b.canonical_id: b.model.lower() for b in CAMERA_BODIES}
    for cid in found:
        model = models.get(cid, "")
        if any(
            other != cid and model and model != models.get(other, "") and model in models.get(other, "")
            for other in found
        ):
            continue
        keep.append(cid)
    return tuple(keep)


def _family_match(text: str) -> tuple[str, str] | None:
    for product_class, patterns in _FAMILIES:
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return product_class, f"{product_class}:{pattern.pattern[:48]}"
    return None


def classify_listing(title: str, description: str = "") -> ProductClassResult:
    """Resolve PRODUCT CLASS before model identity.

    Accessory tokens win. A camera model in an accessory title is compatibility.
    Title-level accessory families beat description noise. Title-level body
    subjects beat description kit/lens mentions so genuine bodies keep recall.
    """
    title = title or ""
    blob = f"{title}\n{description or ''}"
    compat = compatible_cameras(blob)
    title_family = _family_match(title)
    blob_family = _family_match(blob)

    def _incidental_body(family: tuple[str, str] | None) -> bool:
        if not family or family[0] not in {BATTERY, CASE, BOX_ONLY, CHARGER, LENS, KIT}:
            return False
        if family[0] == BOX_ONLY and re.search(r"\b(empty\s+box|box\s+only)\b", title, re.I):
            return False
        if family[0] == LENS and re.search(
            r"\b(with\s+(?:kit\s+)?lens|\+\s*(?:fe|rf|xf|lens)|lens\s+kit)\b", title, re.I
        ):
            return False
        if family[0] == KIT and re.search(r"\b(lens\s+kit|with\s+lens|\+\s*lens)\b", title, re.I):
            return False
        if family[0] == LENS:
            return False
        return bool(_BODY_ONLY.search(title) or (_BODY_SUBJECT.search(title) and _INCIDENTAL.search(title)))

    # Spare batteries / original box on a body listing are not the product.
    if _incidental_body(title_family) or _incidental_body(blob_family):
        return ProductClassResult(CAMERA_BODY, "body_subject_incidental_accessory", compat)

    # Title accessory families always win. Compatibility is not identity.
    if title_family and title_family[0] in ACCESSORY_CLASSES:
        return ProductClassResult(title_family[0], title_family[1], compat)

    # Genuine body titles must not be stolen by a kit-lens mention in the description.
    if _BODY_SUBJECT.search(title) or _BODY_ONLY.search(title):
        return ProductClassResult(CAMERA_BODY, "body_subject", compat)

    family = blob_family
    if family:
        product_class, reason = family
        if product_class == LENS and _BODY_ONLY.search(blob) and not re.search(
            r"\b(with\s+(?:kit\s+)?lens|\+\s*(?:fe|rf|xf|lens)|lens\s+kit)\b", blob, re.I
        ):
            return ProductClassResult(CAMERA_BODY, "body_only_not_lens_listing", compat)
        if product_class == KIT and _BODY_ONLY.search(title) and not re.search(
            r"\b(lens\s+kit|with\s+lens|\+\s*lens)\b", title, re.I
        ):
            return ProductClassResult(CAMERA_BODY, "body_only_kit_word_incidental", compat)
        return ProductClassResult(product_class, reason, compat)

    if _COMPAT_FOR.search(title) and compat and not _BODY_SUBJECT.search(title):
        return ProductClassResult(OTHER_ACCESSORY, "for_or_compatible_with_camera", compat)

    if _BODY_SUBJECT.search(blob) or _BODY_ONLY.search(blob):
        return ProductClassResult(CAMERA_BODY, "body_subject", compat)

    if compat and re.search(r"\b(mirrorless|camera\s+body|bo[iî]tier|gehäuse)\b", blob, re.I):
        return ProductClassResult(CAMERA_BODY, "camera_noun", compat)

    if compat and _COMPAT_FOR.search(blob):
        return ProductClassResult(OTHER_ACCESSORY, "for_or_compatible_with_camera", compat)

    if compat:
        return ProductClassResult(CAMERA_BODY, "supported_model_listing", compat)

    return ProductClassResult(UNKNOWN, "unclassified", compat)


def is_camera_body(product_class: str | None) -> bool:
    return (product_class or "") == CAMERA_BODY
