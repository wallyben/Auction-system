"""Regression tests for the real-money audit failures."""

from datetime import datetime, timezone
from decimal import Decimal

from app.comps.matcher import match_comp
from app.condition.engine import assess_condition
from app.evidence.classes import EvidenceClass, evidence_class_for
from app.exits.engine import compare_exits
from app.identity.resolvers import identify_with_resolvers
from app.models.enums import EvidenceType, IdentityLevel
from app.opportunity.ranking import RANK_REJECTED, RANK_UNVALUED, RANK_WATCH_HIGH_EVIDENCE, commercial_rank
from app.sold.match import variant_reject
from app.sources.ebay_filters import reject_title
from app.valuation.engine import Comp, value_from_comps


def test_ddj_stand_is_not_controller() -> None:
    ident = identify_with_resolvers(title="Pioneer DDJ-FLX10 Stand")
    assert ident.product_class == "accessory"
    assert ident.level in {IdentityLevel.CATEGORY, IdentityLevel.UNKNOWN, IdentityLevel.FAMILY}
    assert reject_title("Pioneer DDJ-FLX10", "Pioneer DDJ-FLX10 Stand") == "accessory"
    assert match_comp("Pioneer DDJ-FLX10 4-Channel DJ Controller", "Pioneer DDJ-FLX10 Stand").accepted is False


def test_case_is_not_camera() -> None:
    ident = identify_with_resolvers(title="Sony A7 IV leather case")
    assert ident.product_class == "accessory"
    assert ident.level != IdentityLevel.EXACT
    assert variant_reject("Sony A7 IV body", "Sony A7 IV leather case") == "accessory"


def test_console_game_is_not_console() -> None:
    ident = identify_with_resolvers(title="PS5 FIFA 24")
    assert ident.product_class == "game"
    assert reject_title("PlayStation 5", "PS5 FIFA 24") == "console_game"


def test_skin_is_not_console_or_controller() -> None:
    ident = identify_with_resolvers(title="Pioneer DDJ-1000 SRT Skin Protective Decal")
    assert ident.product_class == "accessory"
    assert reject_title("Pioneer DDJ-1000", "Pioneer DDJ-1000 SRT Skin Protective Decal") == "accessory"


def test_a7r_is_not_a7_iv() -> None:
    a7 = identify_with_resolvers(title="Sony A7 IV body")
    a7r = identify_with_resolvers(title="Sony A7R IV ILCE-7RM4")
    assert a7.canonical_key != a7r.canonical_key
    assert variant_reject("Sony A7 IV body", "Sony A7R IV ILCE-7RM4") in {"a7r_not_a7", "wrong_generation_a7r", "different_variant"}


def test_pro_max_is_not_pro() -> None:
    assert variant_reject("Apple iPhone 15 Pro 256GB", "iPhone 15 Pro Max 256GB") == "iphone_pro_max_mismatch"
    pro = identify_with_resolvers(title="Apple iPhone 15 Pro 256GB Unlocked")
    pro_max = identify_with_resolvers(title="Apple iPhone 15 Pro Max 256GB")
    assert "pro max" not in (pro.model or "").lower()
    assert pro.canonical_key != pro_max.canonical_key


def test_storage_128_is_not_256() -> None:
    assert variant_reject("iPhone 15 Pro 128GB", "iPhone 15 Pro 256GB") == "storage_mismatch"


def test_gpu_ti_super_laptop_distinctions() -> None:
    assert variant_reject("RTX 4070 12GB", "Gigabyte RTX 4070 SUPER WINDFORCE") in {"gpu_super_mismatch", "4070_super_mismatch"}
    assert variant_reject("RTX 4070 12GB", "RTX 4070 Ti 12GB") == "4070_ti_mismatch"
    laptop = identify_with_resolvers(title="ASUS laptop RTX 4070 mobile")
    assert laptop.level in {IdentityLevel.FAMILY, IdentityLevel.CATEGORY, IdentityLevel.VARIANT}
    assert "laptop" in (laptop.variant or laptop.canonical_key)


def test_lens_generation_mismatch() -> None:
    assert variant_reject("Sony FE 24-70mm GM", "Sony FE 24-70mm GM II") in {"wrong_generation_gm_ii", "different_variant"}


def test_macbook_chip_ram_storage_size() -> None:
    air = identify_with_resolvers(title="Apple MacBook Air 2025 15-inch Midnight Laptop, M3 Chip, 16GB RAM, 256GB")
    pro = identify_with_resolvers(title="MacBook Pro 14 M3 Pro 18GB 512GB")
    assert air.canonical_key != pro.canonical_key
    assert variant_reject(
        "MacBook Air 15 M3 16GB 256GB",
        "MacBook Pro 14 M3 Pro 18GB 512GB",
    ) in {"mac_air_pro_mismatch", "mac_chip_mismatch", "mac_size_mismatch", "different_variant"}


def test_reverb_ask_is_not_realised() -> None:
    now = datetime.now(timezone.utc)
    comps = [
        Comp(
            source="reverb",
            url="https://reverb.com/x",
            title="Pioneer DDJ-FLX10",
            price_eur=Decimal("1391"),
            evidence_type=EvidenceType.CURRENT_ASKING,
            country="US",
            condition_score=Decimal("0.8"),
            product_score=Decimal("0.9"),
            observed_at=now,
            evidence_class="F",
        )
    ]
    result = value_from_comps(comps)
    assert result.realised_count == 0
    assert result.expected_sale_eur == Decimal("0.00")
    assert result.value_status == "UNVALIDATED_VALUE"
    assert result.asking_implied_eur > Decimal("0")
    assert evidence_class_for(EvidenceType.CURRENT_ASKING, source="reverb") is EvidenceClass.F


def test_dealer_model_is_not_a_quote() -> None:
    result = compare_exits(expected_sale_eur=Decimal("1000"), category="cameras", trade_in_evidence=False)
    dealer = next(q for q in result.quotes if q.channel == "dealer")
    assert dealer.confidence <= Decimal("0.25")
    assert dealer.data_backed is False
    assert "MODELLED_DEALER_ESTIMATE" in dealer.notes
    assert result.best_expected_exit != "dealer"
    assert result.safest_exit != "dealer"


def test_owner_order_is_class_c_not_market_wide() -> None:
    assert evidence_class_for(EvidenceType.OWNER_RECORDED, source="ebay_owner_fulfillment") is EvidenceClass.C
    assert evidence_class_for(EvidenceType.REALISED_SALE, source="ebay_marketplace_insights") is EvidenceClass.A


def test_asking_spread_cannot_outrank_realised() -> None:
    fake = commercial_rank(
        money_ready_decision="REVIEW",
        identity_level=IdentityLevel.CATEGORY,
        product_class="accessory",
        realised_count=0,
        expected_profit=Decimal("850"),
        valuation_confidence=Decimal("0.17"),
        failed_gates=["PRICE_EVIDENCE_PASS"],
    )
    real = commercial_rank(
        money_ready_decision="WATCH",
        identity_level=IdentityLevel.EXACT,
        identity_confidence=Decimal("0.92"),
        product_class="primary",
        realised_count=4,
        binding_count=4,
        expected_profit=Decimal("100"),
        valuation_confidence=Decimal("0.84"),
        liquidity_score=Decimal("0.6"),
        downside_profit=Decimal("20"),
        failed_gates=["MAX_BUY_PASS"],
    )
    assert fake.group == RANK_REJECTED
    assert real.group == RANK_WATCH_HIGH_EVIDENCE
    assert real.group_order < fake.group_order


def test_unvalidated_asking_only_is_labelled() -> None:
    rank = commercial_rank(
        money_ready_decision="REVIEW",
        identity_level=IdentityLevel.EXACT,
        identity_confidence=Decimal("0.92"),
        product_class="primary",
        realised_count=0,
        expected_profit=Decimal("800"),
        failed_gates=["PRICE_EVIDENCE_PASS"],
    )
    assert rank.group == RANK_UNVALUED
    assert rank.value_status == "UNVALIDATED_VALUE"


def test_structured_occasion_is_used_not_unknown() -> None:
    result = assess_condition("Occasion")
    assert result.grade.value == "good"
    assert result.confidence >= Decimal("0.75")


def test_irish_panel_skips_owner_and_aggregates() -> None:
    from app.sold.provider import IrishPanelProvider

    joined = " ".join(str(c) for c in IrishPanelProvider.search_realised_sales.__code__.co_consts)
    assert "owner_recorded" in joined
    assert "ticket_level" in joined


def test_insights_probe_without_token_is_blocked() -> None:
    import asyncio

    from app.sold.insights import EbayMarketplaceInsightsProvider

    result = asyncio.run(EbayMarketplaceInsightsProvider().probe(None))
    assert result["entitlement_result"] == "AUTH_ERROR"
    assert result["EBAY_MARKETPLACE_INSIGHTS"] == "BLOCKED_EXTERNAL_ACCESS"


def test_strict_identity_rejects_wrong_macbook_variant() -> None:
    verdict = match_comp(
        "Apple MacBook Air 15 M3 16GB 256GB",
        "MacBook Pro 16 M3 Max 48GB 1TB",
        strict_identity=True,
    )
    assert verdict.accepted is False
