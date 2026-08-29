"""Product-class-first identity: accessories never inherit camera-body identity."""

from __future__ import annotations

from app.identity.product_class import CAMERA_BODY, classify_listing
from app.identity.resolvers import identify_with_resolvers
from app.sold.cameras import CAMERA_BODIES

BODY_IDS = {body.canonical_id for body in CAMERA_BODIES}

LIVE_FALSE_POSITIVES = (
    ("Hersmay EOS R6 II/III cage", "cage"),
    ("SmallRig R6 II cage 4161", "cage"),
    ("Canon BG-R20 battery grip", "battery_grip"),
    ("Canon BG-R10 battery grip", "battery_grip"),
    ("Sony ECM-B1M microphone", "microphone"),
    ("SmallRig cage for Canon EOS R6 Mark II", "cage"),
    ("Canon BG-R20 Battery Grip for EOS R5 Mark II", "battery_grip"),
    ("Sony ECM-B1M Shotgun Microphone for A7 IV", "microphone"),
)

GENUINE_BODIES = (
    "Sony A7 IV body only",
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


def _assert_not_body(title: str, expected_class: str | None = None) -> None:
    classified = classify_listing(title)
    ident = identify_with_resolvers(title=title)
    assert classified.product_class != CAMERA_BODY, title
    assert ident.product_class != CAMERA_BODY, (title, ident.product_class, ident.canonical_key)
    assert ident.canonical_key not in BODY_IDS, (title, ident.canonical_key)
    if expected_class:
        assert classified.product_class == expected_class, (title, classified.product_class)


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
