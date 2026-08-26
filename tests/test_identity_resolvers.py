from decimal import Decimal

from app.identity.resolvers import identify_with_resolvers


def test_gm_ii_is_not_gm_i() -> None:
    first = identify_with_resolvers(title="Sony FE 24-70mm GM lens")
    second = identify_with_resolvers(title="Sony FE 24-70mm GM II")
    assert first.variant == "GM I"
    assert second.variant == "GM II"
    assert first.canonical_key != second.canonical_key


def test_rtx_4080_is_not_super() -> None:
    base = identify_with_resolvers(title="NVIDIA RTX 4080 16GB")
    super_ = identify_with_resolvers(title="NVIDIA RTX 4080 SUPER 16GB")
    assert "super" not in (base.model or "").lower()
    assert "super" in (super_.model or "").lower()


def test_a7_iii_is_not_a7_iv() -> None:
    iii = identify_with_resolvers(title="Sony A7 III body")
    iv = identify_with_resolvers(title="Sony A7 IV body")
    assert iii.canonical_key != iv.canonical_key


def test_ps5_digital_is_not_disc() -> None:
    disc = identify_with_resolvers(title="PlayStation 5 Disc")
    digital = identify_with_resolvers(title="PlayStation 5 Digital")
    assert disc.variant != digital.variant


def test_macbook_without_chip_is_family() -> None:
    ident = identify_with_resolvers(title="MacBook Pro 14")
    assert ident.level.value in {"family", "variant"}
    assert ident.confidence < Decimal("0.80")


def test_gm_ii_70_200_is_not_24_70() -> None:
    first = identify_with_resolvers(title="Sony FE 24-70mm F2.8 GM II")
    tele = identify_with_resolvers(title="Sony FE 70-200mm GM II")
    assert first.variant == "GM II"
    assert tele.variant == "GM II"
    assert first.canonical_key != tele.canonical_key
    assert first.confidence >= Decimal("0.90")
    assert tele.confidence >= Decimal("0.90")


def test_iphone_15_pro_256_is_exact() -> None:
    ident = identify_with_resolvers(title="Apple iPhone 15 Pro 256GB Unlocked")
    assert ident.family == "iPhone"
    assert "pro max" not in (ident.model or "").lower()
    assert ident.level.value == "exact"
    assert ident.confidence >= Decimal("0.90")


def test_ilce_7m4_is_a7_iv() -> None:
    ident = identify_with_resolvers(title="Sony ILCE-7M4 body only")
    assert ident.model == "A7 IV"
    assert ident.level.value == "exact"
    assert ident.confidence >= Decimal("0.90")
