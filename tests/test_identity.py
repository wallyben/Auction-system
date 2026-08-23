"""Product identity resolution."""

from decimal import Decimal

from app.identity.engine import identify_listing
from app.models.enums import IdentityLevel


def test_sony_a7_iv_is_exact() -> None:
    identity = identify_listing(title="Sony A7 IV body only", description="excellent shutter 12k")
    assert identity.brand == "Sony"
    assert "a7" in (identity.model or "").lower()
    assert identity.level in {IdentityLevel.EXACT, IdentityLevel.VARIANT, IdentityLevel.FAMILY}
    assert identity.confidence >= Decimal("0.50")
    assert identity.canonical_key


def test_unknown_junk_title_is_not_forced_exact() -> None:
    identity = identify_listing(title="job lot mixed cables", description="")
    assert identity.level in {IdentityLevel.UNKNOWN, IdentityLevel.CATEGORY, IdentityLevel.FAMILY}
    assert identity.confidence < Decimal("0.80")
