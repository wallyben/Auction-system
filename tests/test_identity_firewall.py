"""Product-class-first identity: accessories never inherit camera-body identity."""

from __future__ import annotations

from app.identity.product_class import CAMERA_BODY, classify_listing, is_camera_body
from app.identity.resolvers import identify_with_resolvers
from app.sold.cameras import CAMERA_BODIES, camera_from_identity, token_in

BODY_IDS = {body.canonical_id for body in CAMERA_BODIES}

# Exact or representative titles from the 2026-09-01 live current book.
LIVE_FALSE_POSITIVES = (
    ("Hersmay EOS R6 II/III cage", "cage"),
    ("SmallRig R6 II cage 4161", "cage"),
    ("Canon BG-R20 battery grip", "battery_grip"),
    ("Canon BG-R10 battery grip", "battery_grip"),
    ("Sony ECM-B1M microphone", "microphone"),
    ("SmallRig cage for Canon EOS R6 Mark II", "cage"),
    ("Canon BG-R20 Battery Grip for EOS R5 Mark II", "battery_grip"),
    ("Sony ECM-B1M Shotgun Microphone for A7 IV", "microphone"),
    ("Hersmay EOS R6 II / III Camera For Canon R6II, R6II/III", "cage"),
    ("SmallRig R6 Mark II Camera Cage for Canon EOS R6 Mark II Mirrorless Camera 4161", "cage"),
    ("Canon BG-R20 Battery Grip for EOS R5,6 Mark II/EOS R5,6 [Top Mint]", "battery_grip"),
    ("Canon BG-R10 Battery Grip for EOS R5, R6 Mirrorless Camera [Top Mint]", "battery_grip"),
    ("Sony A7 IV ILCE-7M4 LCD Screen Replacement Genuine Sony Spare", "parts"),
    ("L Plate Bracket Sony Alpha A7R mark IV ILCE A7R4 - Made in USA", "cage"),
    ("Canon RF 24-70mm F2.8L IS USM Lens with Box", "lens"),
    ("NIKON Z7 II Z6 II Digital Camera Reference Manual - WIRE BOUND - TOUGH COVERS", "manual"),
    ("Compatible NIKON Z6II Z7II Z5 Z6 Z7 Shutter Group Unit Assembly with Blade Part", "parts"),
    ("Canon EOS R6 CMOS Image Sensor Parts CY3-1915-000_0.15_5", "parts"),
    ("Sony Alpha A7 A7I/ II/ III A7M1/ A7M2/A7M3 Mirrorless Digital Camera CMOS Sensor", "parts"),
    ("HP NVIDIA GeForce RTX 4070 SUPER 12GB GDDR6X Graphics Card – Ada Lovelace | DLS", None),
    ("HP NVIDIA GeForce RTX 4070 Super 12GB GDDR6X - GPU non-LHR - PC Omen 40L Desktop", None),
    ("ASUS TUF Gaming GeForce RTX™ 4070 12GB GDDR6X OC Edition", None),
    ("ASUS NVIDIA GeForce RTX 4070 TUF Gaming Graphics Card 12GB OC Edition", None),
    ("GIGABYTE GeForce RTX 4070Ti SUPER WINDFORCE MAX OC D6X 16GB Gaming Graphics Card", None),
    ("MSI NVIDIA GeForce RTX 4080 Gaming x Trio 16GB GRAPHICS CARD (GPU)", None),
    ("RTX 4080 ZOTAC Gaming trinity", None),
    ("Gigabyte GeForce RTX 5070 Ti Windforce OC SFF 16GB GDDR7 Graphics Card", None),
    ("Shure SM7B Cardioid Dynamic Vocal Broadcast Microphone Sealed in box Black", None),
    ("SHURE SM7B Cardioid Dynamic Vocal Microphone Studio Podcast Mic New Open Box", None),
    ("Authentique Microphone Dynamique Cardioïde Shure SM7B", None),
)

GENUINE_BODIES = (
    "Sony A7 IV body only",
    "Canon EOS R6 body",
    "Canon EOS R6 Mark II Mirrorless Camera Body",
    "Fujifilm X-T5 body",
    "Sony A7 III body",
    "Sony ILCE-7M4 body only",
    "Canon EOS R5 body only",
    "Nikon Z6 II body only",
    "Fujifilm X-T4 body",
    "Sony A7 IV for sale",
)

ADVERSARIAL_TEMPLATES = (
    ("SmallRig cage for {name}", "cage"),
    ("battery grip for {name}", "battery_grip"),
    ("microphone compatible with {name}", "microphone"),
    ("charger for {name}", "charger"),
    ("case for {name}", "case"),
    ("L bracket for {name}", "cage"),
    ("screen protector for {name}", "screen_protector"),
    ("battery for {name}", "battery"),
    ("replacement door for {name}", "parts"),
    ("dummy battery for {name}", "battery"),
    ("manual for {name}", "manual"),
    ("box only for {name}", "box_only"),
)

TOKEN_TITLES = (
    "GDDR6",
    "GDDR6X",
    "DDR6",
    "RTX 4060",
    "RTX 4070",
    "RTX 4080",
    "SM7B",
    "RTX 4070 12GB GDDR6X",
)


def _assert_not_body(title: str, expected_class: str | None = None) -> None:
    classified = classify_listing(title)
    ident = identify_with_resolvers(title=title)
    assert classified.product_class != CAMERA_BODY, title
    assert ident.product_class != CAMERA_BODY, (title, ident.product_class, ident.canonical_key)
    assert not is_camera_body(ident.product_class), title
    assert ident.canonical_key not in BODY_IDS, (title, ident.canonical_key)
    if expected_class:
        assert classified.product_class == expected_class, (title, classified.product_class)
    # _comps_for only loads camera-body sold tickets when product_class is camera_body.
    assert not is_camera_body(classified.product_class)


def test_live_accessory_false_positives_are_zero() -> None:
    for title, expected in LIVE_FALSE_POSITIVES:
        _assert_not_body(title, expected)


def test_adversarial_accessories_for_every_supported_body() -> None:
    for body in CAMERA_BODIES:
        name = body.aliases[0]
        for template, expected in ADVERSARIAL_TEMPLATES:
            _assert_not_body(template.format(name=name), expected)


def test_genuine_bodies_keep_camera_body_identity() -> None:
    for title in GENUINE_BODIES:
        classified = classify_listing(title)
        ident = identify_with_resolvers(title=title)
        assert classified.product_class == CAMERA_BODY, (title, classified.product_class, classified.reason)
        assert ident.product_class == CAMERA_BODY, (title, ident.product_class)
        assert ident.canonical_key in BODY_IDS, (title, ident.canonical_key)


def test_compatibility_is_not_canonical_identity() -> None:
    ident = identify_with_resolvers(title="SmallRig cage for Canon EOS R6 Mark II")
    assert ident.product_class == "cage"
    assert "canon|r6-ii|body" in ident.compatible_camera_ids
    assert ident.canonical_key != "canon|r6-ii|body"
    assert ident.canonical_key not in BODY_IDS


def test_gddr6_and_rtx_tokens_are_not_canon_r6() -> None:
    from app.identity.product_class import compatible_cameras

    for title in TOKEN_TITLES:
        assert "canon|r6|body" not in compatible_cameras(title), title
        assert not token_in(title.lower(), "r6"), title
        classified = classify_listing(title)
        ident = identify_with_resolvers(title=title)
        assert classified.product_class != CAMERA_BODY, (title, classified.product_class)
        assert ident.canonical_key not in BODY_IDS, (title, ident.canonical_key)
        assert camera_from_identity(brand=None, model=None, title=title) is None, title

    r6 = "Canon EOS R6 body"
    assert token_in(r6.lower(), "r6")
    assert "canon|r6|body" in compatible_cameras(r6)
    ident = identify_with_resolvers(title=r6)
    assert ident.product_class == CAMERA_BODY
    assert ident.canonical_key == "canon|r6|body"

    assert token_in("eos r6", "r6")
    assert token_in("r6 ii", "r6")
    assert not token_in("gddr6x", "r6")
    assert not token_in("gddr6", "r6")
    assert not token_in("ddr6", "r6")
    assert not token_in("rtx 4070 12gb gddr6x", "r6")
    assert not token_in("sm7b", "r6")
