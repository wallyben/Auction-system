"""Regression fixtures from real production listing titles (2026-08 live scan)."""

from decimal import Decimal

from app.condition.engine import assess_condition
from app.identity.resolvers import identify_with_resolvers
from app.models.enums import IdentityLevel
from app.sources.ebay_filters import reject_title

# (query, title, expected_reject or None)
LIVE_FP_CASES = [
    ("Pioneer DDJ-FLX10", "Pioneer DDJ-FLX10 Stand", "accessory"),
    ("Pioneer DDJ-1000", "Power socket for Pioneer DDJ-1000 DKN1649", "accessory"),
    ("Pioneer DDJ-1000", "Pioneer DDJ-1000 SRT Skin Protective Decal", "accessory"),
    ("iPhone 16 Pro 256GB", "BOITE iPhone 16 PRO max 256gb", "accessory"),
    ("PlayStation 5", "PS5 APU Foam Pad Insulation", "accessory"),
    ("PlayStation 5", "Playstation 5 PRO 2 TB come nuova", "ps5_pro_mismatch"),
    ("PlayStation 5", "Playstation 5 PRO Faceplates", "accessory"),
    ("Sony A7 IV", "Sony A7R IV ILCE-7RM4", "wrong_generation_a7r"),
    ("iPhone 15 Pro 256GB", "iPhone 15 Pro Max 256GB", "iphone_pro_max_mismatch"),
    ("RTX 4070", "Gigabyte RTX 4070 SUPER WINDFORCE", "4070_super_mismatch"),
    ("Sony FE 24-70mm GM II", "GM II Moving Barrel replacement repair", "accessory"),
]

LIVE_KEEP = [
    ("Sony A7 IV", "Sony A7 IV ILCE-7M4 body"),
    ("Sony FE 24-70mm GM II", "Sony FE 24-70mm F2.8 GM II"),
    ("iPhone 15 Pro 256GB", "Apple iPhone 15 Pro 256GB Unlocked 96% BH"),
    ("PlayStation 5", "Sony PlayStation 5 Disc Console"),
    ("RTX 4070", "NVIDIA GeForce RTX 4070 12GB"),
    ("Shure SM7B", "Shure SM7B Cardioid Dynamic Vocal Microphone"),
    ("Pioneer DDJ-FLX10", "Pioneer DDJ-FLX10 4-Channel DJ Controller"),
    ("MacBook Pro 14 M3", "MacBook Pro 14 M3 Pro 18GB 512GB"),
]


def test_live_false_positives_are_rejected() -> None:
    for query, title, reason in LIVE_FP_CASES:
        assert reject_title(query, title) == reason, (query, title)


def test_live_genuine_titles_are_kept() -> None:
    for query, title in LIVE_KEEP:
        assert reject_title(query, title) is None, (query, title)


def test_live_identity_exact_or_variant() -> None:
    for _, title in LIVE_KEEP:
        ident = identify_with_resolvers(title=title)
        assert ident.level in {IdentityLevel.EXACT, IdentityLevel.VARIANT}, (title, ident.level, ident.confidence)
        assert ident.confidence >= Decimal("0.80"), (title, ident.confidence)


def test_live_used_condition_passes_bar() -> None:
    result = assess_condition("Used", "Please read. Battery health 96%.")
    assert result.confidence >= Decimal("0.75")
