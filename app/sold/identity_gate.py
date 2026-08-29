"""ARIE PRODUCT_IDENTITY_VALIDATION for sold camera comps.

CompSniper relevance cleanup is not trusted. Every returned sold record must
pass this gate before it becomes valuation evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.identity.resolvers import identify_with_resolvers
from app.identity.schemas import parse_camera
from app.models.enums import IdentityLevel
from app.sold.cameras import CAMERA_BODIES, CameraBody, camera_from_identity
from app.sold.condition_map import SOLD_PARTS, map_sold_condition
from app.sources.ebay_filters import ACCESSORY_RE, KIT_RE, REPAIR_RE

PRODUCT_CLASS_CAMERA_BODY = "camera_body"

_LENS = re.compile(
    r"\b("
    r"lens|obiettivo|objectif|objektiv|zoom\s+lens|prime\s+lens|"
    r"(?:fe|ef|rf)\s*\d{2,3}(?:\s*mm)?"
    r")\b",
    re.I,
)
# Only body-only language. ILCE-/EOS R/X-T are model tokens and must not
# skip lens rejection on kit titles such as "ILCE-7M3 Digital Camera + FE 50mm".
_BODY_TOKEN = re.compile(
    r"\b(body|body\s+only|boitier|boîtier|gehäuse|solo\s+cuerpo|solo\s+corpo)\b",
    re.I,
)
# "+ FE 50mm", "+ SEL2870 28-70mm", "+ Sigma 18-50mm", "with TTArtisan AF 56mmF1.8"
# even when "body" is present. Do not treat "+ extras" / "+ batteries" as kits.
_LENS_ADDON = re.compile(
    r"("
    r"\+\s*(?:fe|ef|rf|xf|xc|e[\s-]?mount|lens|obiettivo|objectif|objektiv)\b"
    r"|\+\s*(?:sel\d+)\b"
    r"|\+\s*(?:sigma|tamron|tokina|samyang|viltrox|ttartisan|voigtlander)\b"
    r"|\+\s*(?!extras?\b|extra\b|accessories\b|batter(?:y|ies)\b|cf\b|cards?\b|charger\b)"
    r"[^,\n]{0,50}\d{2,3}(?:\s*-\s*\d{2,3})?\s*mm\b"
    r"|\+\s*\d{2,3}(?:\s*-\s*\d{2,3})?\s*mm\b"
    r"|\+\s*\d{2,3}\s*-\s*\d{2,3}\b"
    r"|\+\s*(?:fe|ef|rf|xf|xc)?\s*\d(?:\.\d)?\s*/\s*\d{2,3}"
    r"|\bwith\s+(?:(?:fe|ef|rf|xf|xc)\s+)?(?:lens|\d{2,3}(?:\s*-\s*\d{2,3})?\s*mm)\b"
    r"|\bwith\s+(?:[a-z][\w-]*\s+){0,4}\d{2,3}(?:\s*-\s*\d{2,3})?\s*mm"
    r"|\(\s*(?:with|w/)\s+[^)]*\d{2,3}(?:\s*-\s*\d{2,3})?\s*mm"
    r"|\b(?:xf|xc)\s*\d{2,3}(?:\s*-\s*\d{2,3})?(?:\s*mm)?\b"
    r"|\bsel\d{3,}\b"
    r"|\b\d+\s+(?:[a-z]+\s+){0,3}lenses\b"
    r")",
    re.I,
)
_WRONG_SONY = {
    "A7 III": re.compile(r"\b(a7\s*iv|a7iv|ilce-7m4|a7r|a7s|a7c|a7cr)\b", re.I),
    "A7 IV": re.compile(r"\b(a7\s*iii|a7iii|ilce-7m3|a7r|ilce-7rm|a7s|ilce-7sm|a7c|a7cr)\b", re.I),
    "A7R III": re.compile(r"\b(a7r\s*iv|a7riv|ilce-7rm4|a7\s*iv|a7s|a7c)\b", re.I),
    "A7R IV": re.compile(r"\b(a7r\s*iii|a7riii|ilce-7rm3|a7\s*iv(?!r)|ilce-7m4|a7s|a7c)\b", re.I),
    "A7S III": re.compile(r"\b(a7\s*iv|a7r|a7c|a7s\s*ii(?!i))\b", re.I),
}
_WRONG_CANON = {
    "EOS R6": re.compile(r"\b(r6\s*ii|r6\s*mark\s*ii|r6ii|r5|r7|r8|r10|r50|rp)\b", re.I),
    "EOS R6 II": re.compile(r"\b(r5|r7|r8|r10|rp)\b", re.I),
    "EOS R5": re.compile(r"\b(r5c|r5\s*ii|r5ii|r6)\b", re.I),
}
_WRONG_NIKON = {
    "Z6 II": re.compile(r"\b(z7|z8|z9|z5|z6\s*iii|z6iii|z50|z30|zfc)\b", re.I),
    "Z7 II": re.compile(r"\b(z6|z8|z9|z5|z50)\b", re.I),
}
_WRONG_FUJI = {
    "X-T4": re.compile(r"\b(x-?t5|x-?t3|x-?h2|x-?s20|x-?t30)\b", re.I),
    "X-T5": re.compile(r"\b(x-?t4|x-?t3|x-?h2|x-?s20)\b", re.I),
}

CAMERA_ACCESSORY_RE = re.compile(
    r"\b("
    r"cage|smallrig|case|cover|leather\s+half|silicone|"
    r"battery(?!\s+grip\s+included)|np-fz\d+|charger|power\s+adapter|"
    r"screen\s+protector|tempered\s+glass|(?:user\s+|instruction\s+)?manuals?(?!\s+focus)|empty\s+box|"
    r"straps?|body\s+cap|hot\s+shoe|thumb\s+grip|"
    r"dummy|display\s+model|housing\s+only"
    r")\b",
    re.I,
)


@dataclass(slots=True)
class IdentityVerdict:
    accepted: bool
    reason: str
    product_class: str
    canonical_product_id: str
    variant: str
    identity_level: str
    target_model: str = ""


def _wrong_family(body: CameraBody, title: str) -> str | None:
    tables = (_WRONG_SONY, _WRONG_CANON, _WRONG_NIKON, _WRONG_FUJI)
    for table in tables:
        pattern = table.get(body.model)
        if pattern and pattern.search(title):
            return "wrong_model_family"
    return None


def validate_camera_sold(
    *,
    target: CameraBody | None = None,
    target_title: str = "",
    sold_title: str,
    sold_condition_raw: str | None = None,
    sold_condition_id: str | int | None = None,
    valuing_parts: bool = False,
) -> IdentityVerdict:
    """Accept only exact CAMERA_BODY comps for the target identity."""
    title = sold_title or ""
    body = target or camera_from_identity(brand=None, model=None, title=target_title)
    if body is None:
        parsed = parse_camera(target_title)
        if parsed and parsed.model:
            body = camera_from_identity(brand=parsed.manufacturer, model=parsed.model, title=target_title)
    if body is None:
        return IdentityVerdict(False, "unknown_target_identity", "unknown", "", "", IdentityLevel.UNKNOWN.value)

    ident = identify_with_resolvers(title=title)
    cond = map_sold_condition(sold_condition_raw, condition_id=sold_condition_id, title=title)

    if ident.product_class == "accessory" or CAMERA_ACCESSORY_RE.search(title) or ACCESSORY_RE.search(title):
        return IdentityVerdict(
            False, "accessory", "accessory", body.canonical_id, "body", ident.level.value, body.model
        )
    if (KIT_RE.search(title) or re.search(r"\bkit\b", title, re.I)) and not re.search(
        r"\bbody\s+only\b", title, re.I
    ):
        return IdentityVerdict(
            False, "kit_or_bundle", "camera_kit", body.canonical_id, "kit", ident.level.value, body.model
        )
    if _LENS_ADDON.search(title):
        return IdentityVerdict(
            False, "kit_or_bundle", "camera_kit", body.canonical_id, "kit", ident.level.value, body.model
        )
    if REPAIR_RE.search(title) or cond.grade == SOLD_PARTS:
        if not valuing_parts:
            return IdentityVerdict(
                False, "parts_or_broken", "parts", body.canonical_id, "body", ident.level.value, body.model
            )
    if _LENS.search(title) and not _BODY_TOKEN.search(title):
        return IdentityVerdict(
            False, "lens_not_body", "lens", body.canonical_id, "body", ident.level.value, body.model
        )
    family = _wrong_family(body, title)
    if family:
        return IdentityVerdict(
            False, family, ident.product_class or "unknown", body.canonical_id, "body", ident.level.value, body.model
        )

    # Positive identity: alias, MPN, or structured parse of the same model.
    blob = title.lower()
    needles = [body.model.lower(), body.mpn.lower(), *(a.lower() for a in body.aliases)]
    hit = any(n and n.lower() in blob for n in needles)
    sold_parsed = parse_camera(title)
    same_structured = bool(
        sold_parsed
        and sold_parsed.manufacturer
        and sold_parsed.manufacturer.lower() == body.manufacturer.lower()
        and sold_parsed.model
        and sold_parsed.model.lower() == body.model.lower()
    )
    same_resolver = bool(
        ident.brand
        and ident.model
        and ident.brand.lower() == body.manufacturer.lower()
        and body.model.lower() in ident.model.lower()
        and ident.level in {IdentityLevel.EXACT, IdentityLevel.VARIANT}
    )
    if not (hit or same_structured or same_resolver):
        return IdentityVerdict(
            False, "wrong_model", ident.product_class or "unknown", body.canonical_id, "body", ident.level.value, body.model
        )
    if sold_parsed and sold_parsed.body_or_kit == "kit":
        return IdentityVerdict(
            False, "kit_or_bundle", "camera_kit", body.canonical_id, "kit", ident.level.value, body.model
        )
    return IdentityVerdict(
        True,
        "",
        PRODUCT_CLASS_CAMERA_BODY,
        body.canonical_id,
        "body",
        IdentityLevel.EXACT.value,
        body.model,
    )


def identity_precision_corpus() -> list[dict[str, str]]:
    """Deterministic labelled sold titles for precision measurement."""
    a7iv = "sony|a7-iv|body"
    rows: list[dict[str, str]] = []
    exact = [
        "Sony A7 IV Body Only ILCE-7M4",
        "Sony Alpha 7 IV ILCE-7M4 Gehäuse",
        "Sony A7IV body shutter 12k",
        "Sony ILCE-7M4 A7 IV boîtier seul",
        "Sony A7 IV used body UK",
        "SONY ALPHA 7 IV BODY",
        "Sony A7 IV ILCE-7M4 body only excellent",
        "Sony Alpha7 IV body",
        "ILCE-7M4 Sony A7 IV",
        "Sony A7 IV digital camera body",
    ]
    accessories = [
        "Sony A7 IV leather case",
        "SmallRig cage for Sony A7 IV",
        "Sony A7 IV battery NP-FZ100",
        "Sony A7 IV charger BC-QZ1",
        "Sony A7 IV screen protector",
        "Sony A7 IV camera manual",
        "Silicone cover Sony A7 IV",
        "Peak Design strap Sony A7 IV",
        "Sony A7 IV body cap",
        "Hot shoe cover Sony A7 IV",
    ]
    wrong = [
        "Sony A7 III body ILCE-7M3",
        "Sony A7R IV ILCE-7RM4 body",
        "Sony A7S III ILCE-7SM3",
        "Sony A7C body",
        "Sony A7CR body",
        "Sony A7 IV? no Sony A7R IV",
        "Canon EOS R6 body",
        "Nikon Z6 II body",
        "Sony A7 II body",
        "Sony A9 III body",
    ]
    kits = [
        "Sony A7 IV kit 28-70mm",
        "Sony A7 IV + 24-70 GM kit",
        "Sony A7 IV body kit de lentes",
        "Sony A7 IV bundle with lens",
        "Sony A7 IV lot of 2 cameras",
        "Sony A7 IV with FE 24-70",
        "Sony A7 IV kit lens included",
        "Sony Alpha 7 IV zoom kit",
        "Sony A7 IV twin lens kit",
        "Sony A7 IV body plus extras kit",
    ]
    parts = [
        "Sony A7 IV for parts not working",
        "Sony A7 IV broken shutter",
        "Sony A7 IV spares or repair",
        "Sony A7 IV faulty no power",
        "Sony A7 IV pour pièces",
        "Sony A7 IV zur Reparatur",
        "Sony ILCE-7M4 as is repair",
        "Sony A7 IV cracked sensor",
        "Sony A7 IV does not work",
        "Sony A7 IV body for parts",
    ]
    # Additional models, 10 exact + 5 contaminants each to reach 100+.
    others_exact = [
        ("sony|a7-iii|body", "Sony A7 III body only ILCE-7M3"),
        ("sony|a7-iii|body", "Sony Alpha 7 III ILCE-7M3 Gehäuse"),
        ("sony|a7r-iv|body", "Sony A7R IV body ILCE-7RM4"),
        ("sony|a7r-iii|body", "Sony A7R III body ILCE-7RM3"),
        ("canon|r6|body", "Canon EOS R6 body only"),
        ("canon|r6-ii|body", "Canon EOS R6 Mark II body"),
        ("canon|r5|body", "Canon EOS R5 body only"),
        ("nikon|z6-ii|body", "Nikon Z6 II body"),
        ("nikon|z7-ii|body", "Nikon Z7 II body only"),
        ("fujifilm|x-t4|body", "Fujifilm X-T4 body"),
        ("fujifilm|x-t5|body", "Fujifilm X-T5 body only"),
        ("sony|a7-iv|body", "Sony A7 IV ILCE-7M4 used"),
        ("sony|a7-iv|body", "Sony A7 IV camera body shutter 8k"),
        ("canon|r6-ii|body", "Canon R6 II body UK"),
        ("nikon|z6-ii|body", "Nikon Z6II body excellent"),
    ]
    others_bad = [
        ("sony|a7-iii|body", "Sony A7 IV body", "wrong_model_family"),
        ("sony|a7-iii|body", "Sony A7 III leather case", "accessory"),
        ("sony|a7r-iv|body", "Sony A7 IV body", "wrong_model_family"),
        ("canon|r6|body", "Canon EOS R6 II body", "wrong_model_family"),
        ("canon|r6|body", "Canon EOS R6 kit 24-105", "kit_or_bundle"),
        ("canon|r5|body", "Canon EOS R5C body", "wrong_model_family"),
        ("nikon|z6-ii|body", "Nikon Z7 II body", "wrong_model_family"),
        ("nikon|z6-ii|body", "Nikon Z6 II for parts", "parts_or_broken"),
        ("fujifilm|x-t4|body", "Fujifilm X-T5 body", "wrong_model_family"),
        ("fujifilm|x-t5|body", "Fuji X-T5 cage SmallRig", "accessory"),
        ("canon|r6-ii|body", "Canon R6 body (not mark II)", "wrong_model"),
        ("sony|a7r-iii|body", "Sony A7R IV body", "wrong_model_family"),
        ("sony|a7-iv|body", "Sony FE 24-70 GM II lens", "lens_not_body"),
        ("sony|a7-iv|body", "Sony A7C II body", "wrong_model_family"),
        ("canon|r5|body", "Canon R5 battery grip only", "accessory"),
    ]
    more_exact = [
        ("sony|a7-iii|body", "Sony ILCE-7M3 A7 III boîtier"),
        ("sony|a7-iii|body", "Sony A7III body only shutter 45k"),
        ("sony|a7r-iv|body", "Sony Alpha 7R IV Gehäuse"),
        ("sony|a7r-iii|body", "Sony ILCE-7RM3 body only"),
        ("sony|a7s-iii|body", "Sony A7S III body ILCE-7SM3"),
        ("sony|a7s-iii|body", "Sony Alpha 7S III boîtier seul"),
        ("canon|r6|body", "Canon EOS R6 Gehäuse only"),
        ("canon|r6-ii|body", "Canon EOS R6 Mark II boîtier"),
        ("canon|r5|body", "Canon EOS R5 Gehäuse"),
        ("nikon|z6-ii|body", "Nikon Z 6 II body"),
        ("nikon|z7-ii|body", "Nikon Z7II Gehäuse"),
        ("fujifilm|x-t4|body", "Fuji X-T4 boîtier"),
        ("fujifilm|x-t5|body", "Fujifilm XT5 body UK"),
        ("sony|a7-iv|body", "Sony A7 IV ILCE-7M4 Gehäuse only"),
        ("sony|a7-iv|body", "Sony Alpha 7 IV used body DE"),
    ]
    more_bad = [
        ("sony|a7s-iii|body", "Sony A7S III leather case", "accessory"),
        ("sony|a7s-iii|body", "Sony A7 IV body", "wrong_model_family"),
        ("canon|r6-ii|body", "Canon EOS R6 II kit 24-105", "kit_or_bundle"),
        ("canon|r5|body", "Canon EOS R5 for parts", "parts_or_broken"),
        ("nikon|z7-ii|body", "Nikon Z6 II body", "wrong_model_family"),
        ("nikon|z7-ii|body", "Nikon Z7 II strap Peak Design", "accessory"),
        ("fujifilm|x-t4|body", "Fujifilm X-T4 kit 18-55", "kit_or_bundle"),
        ("fujifilm|x-t5|body", "Fujifilm X-T5 broken shutter", "parts_or_broken"),
        ("sony|a7-iii|body", "Sony A7 III charger BC-QZ1", "accessory"),
        ("sony|a7r-iv|body", "Sony A7R IV screen protector", "accessory"),
        ("sony|a7-iv|body", "Sony A7 IV empty box", "accessory"),
        ("canon|r6|body", "Canon R6 battery LP-E6NH", "accessory"),
        ("sony|a7-iv|body", "Sony A7 IV user manual PDF", "accessory"),
        ("sony|a7r-iii|body", "Sony A7R III + 24-70 kit", "kit_or_bundle"),
        ("nikon|z6-ii|body", "Nikon Z6 II cage SmallRig", "accessory"),
        (
            "sony|a7-iii|body",
            "Sony Alpha a7 III ILCE-7M3 Digital Camera + FE 50mm f/1.8",
            "kit_or_bundle",
        ),
        (
            "sony|a7r-iv|body",
            "Sony A7R IV ILCE-7RM4 Body + FE 1.8/50mm etc",
            "kit_or_bundle",
        ),
        ("fujifilm|x-t5|body", "Fujifilm X-T5 + 35mm f/2", "kit_or_bundle"),
        (
            "fujifilm|x-t4|body",
            "Fujifilm X-T4 26.1 MP Mirrorless Camera - Black (with XF 16-80mm f/4 R OIS WR)",
            "kit_or_bundle",
        ),
        (
            "sony|a7-iii|body",
            "Sony Alpha A7 III Camera Body with Tamron 28-75mm F2.8 Lens + More!",
            "kit_or_bundle",
        ),
        (
            "sony|a7-iii|body",
            "Sony Alpha a7 III ILCE-7M3 24.2MP 4K Wi-Fi + SEL2870 28-70mm Black",
            "kit_or_bundle",
        ),
        (
            "fujifilm|x-t4|body",
            "Black Fujifilm X-T4 26.1 MP Mirrorless Camera + Sigma  18-50mm f2.8",
            "kit_or_bundle",
        ),
        (
            "fujifilm|x-t5|body",
            "Fujifilm X-T5 Silver with TTArtisan AF 56mmF1.8 - Very Good Condition",
            "kit_or_bundle",
        ),
        (
            "fujifilm|x-t5|body",
            "Fujifilm X-T5 40.2 MP Mirrorless Digital Camera, 2 Fuji film lenses, Godox flash",
            "kit_or_bundle",
        ),
    ]
    more_exact.append(("sony|a7-iii|body", "Sony A7 III ILCE-7M3 Body Only + extras"))
    for title in exact:
        rows.append({"target": a7iv, "title": title, "label": "exact", "expect_accept": "true"})
    for title in accessories:
        rows.append({"target": a7iv, "title": title, "label": "accessory", "expect_accept": "false"})
    for title in wrong:
        rows.append({"target": a7iv, "title": title, "label": "wrong_model", "expect_accept": "false"})
    for title in kits:
        rows.append({"target": a7iv, "title": title, "label": "kit", "expect_accept": "false"})
    for title in parts:
        rows.append({"target": a7iv, "title": title, "label": "parts", "expect_accept": "false"})
    for cid, title in others_exact:
        rows.append({"target": cid, "title": title, "label": "exact", "expect_accept": "true"})
    for cid, title, _label in others_bad:
        rows.append({"target": cid, "title": title, "label": _label, "expect_accept": "false"})
    for cid, title in more_exact:
        rows.append({"target": cid, "title": title, "label": "exact", "expect_accept": "true"})
    for cid, title, _label in more_bad:
        rows.append({"target": cid, "title": title, "label": _label, "expect_accept": "false"})
    return rows


def measure_identity_precision() -> dict[str, object]:
    corpus = identity_precision_corpus()
    accepted_exact = 0
    accepted_wrong = 0
    rejected = 0
    confusion = {"accessory": 0, "wrong_model": 0, "kit": 0, "parts": 0, "other_bad": 0}
    reasons: dict[str, int] = {}
    by_id = {b.canonical_id: b for b in CAMERA_BODIES}
    for row in corpus:
        body = by_id[row["target"]]
        verdict = validate_camera_sold(target=body, sold_title=row["title"])
        want = row["expect_accept"] == "true"
        if verdict.accepted:
            if want:
                accepted_exact += 1
            else:
                accepted_wrong += 1
                key = row["label"] if row["label"] in confusion else "other_bad"
                confusion[key] = confusion.get(key, 0) + 1
        else:
            rejected += 1
            reasons[verdict.reason] = reasons.get(verdict.reason, 0) + 1
    accepted_n = accepted_exact + accepted_wrong
    precision = (accepted_exact / accepted_n) if accepted_n else 0.0
    return {
        "sample_size": len(corpus),
        "accepted": accepted_n,
        "accepted_exact": accepted_exact,
        "accepted_wrong": accepted_wrong,
        "rejected": rejected,
        "exact_match_precision": round(precision, 4),
        "accessory_contamination": confusion["accessory"] / accepted_n if accepted_n else 0.0,
        "wrong_model_contamination": (confusion["wrong_model"] + confusion.get("wrong_model_family", 0))
        / accepted_n
        if accepted_n
        else 0.0,
        "kit_body_contamination": confusion["kit"] / accepted_n if accepted_n else 0.0,
        "broken_parts_contamination": confusion["parts"] / accepted_n if accepted_n else 0.0,
        "rejection_reasons": reasons,
        "threshold": 0.95,
        "pass": precision >= 0.95 and accepted_wrong == 0,
    }
