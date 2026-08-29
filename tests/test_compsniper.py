"""CompSniper adapter, identity gate, cache, UK proxy, fail-closed BUY_READY."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
import respx

from app.decision.gates import apply_money_ready_gates
from app.evidence.providers.compsniper import (
    CompSniperProvider,
    parse_item,
    parse_money,
    parse_sold_at,
    reset_health_for_tests,
)
from app.market.reference import check_anomaly
from app.models.enums import Decision, EvidenceType, IdentityLevel, MoneyReadyDecision
from app.sold.cache import cache_key, ttl_hours
from app.sold.cameras import camera_by_id, query_plan_for
from app.sold.condition_map import SOLD_GOOD, SOLD_PARTS, map_sold_condition
from app.sold.identity_gate import measure_identity_precision, validate_camera_sold
from app.sold.normalize import normalize_item
from app.valuation.engine import Comp, value_from_comps


def _gates(**overrides):
    data = dict(
        engine=Decision.BUY,
        identity_level=IdentityLevel.EXACT,
        identity_confidence=Decimal("0.92"),
        condition_confidence=Decimal("0.80"),
        valuation_confidence=Decimal("0.82"),
        comparable_count=8,
        realised_count=8,
        local_count=0,
        liquidity_confidence=Decimal("0.55"),
        expected_days=21,
        expected_profit=Decimal("80"),
        downside_profit=Decimal("10"),
        roi=Decimal("0.30"),
        risk_score=Decimal("0.20"),
        high_risk=False,
        asking=Decimal("200"),
        max_buy=Decimal("250"),
        all_in_cost=Decimal("220"),
        purchase_price=Decimal("200"),
        gross_sale=Decimal("350"),
        net_proceeds=Decimal("300"),
        category="cameras",
        category_certified=True,
        exit_present=True,
        provenance_complete=True,
        source_fresh=True,
        tax_modelled=True,
        local_market_method="UK_REALIZED_PROXY",
        uk_comp_count=8,
        localisation_confidence=Decimal("0.55"),
        sold_evidence_fresh=True,
        valuation_anomaly=False,
    )
    data.update(overrides)
    return apply_money_ready_gates(**data)


@pytest.mark.asyncio
async def test_compsniper_auth_missing_key() -> None:
    reset_health_for_tests()
    provider = CompSniperProvider(api_key="", enabled=True)
    page = await provider.scrape("Sony A7 IV")
    assert page.ok is False
    assert page.http_status == 401
    assert page.error_code == "unauthorized"
    health = await provider.healthcheck()
    assert health["status"] == "BLOCKED_CREDENTIALS"


@pytest.mark.asyncio
async def test_compsniper_schema_parsing_and_rate_headers() -> None:
    reset_health_for_tests()
    payload = {
        "keyword": "Sony A7 IV",
        "page": 1,
        "totalItems": 1,
        "hasNextPage": False,
        "items": [
            {
                "itemId": "123",
                "url": "https://www.ebay.co.uk/itm/123",
                "title": "Sony A7 IV Body Only ILCE-7M4",
                "condition": "Used",
                "conditionId": 3000,
                "listingType": "sold",
                "endedAt": "2026-08-01",
                "soldPrice": "1100.00",
                "soldCurrency": "GBP",
                "shippingPrice": "12.50",
                "shippingCurrency": "GBP",
                "totalPrice": "1112.50",
                "sellerUsername": "camshop",
                "bestOfferAccepted": False,
            }
        ],
    }
    with respx.mock:
        respx.get("https://api.compsniper.com/v1/scrape").mock(
            return_value=httpx.Response(
                200,
                json=payload,
                headers={
                    "X-RateLimit-Limit": "60",
                    "X-RateLimit-Remaining": "59",
                    "X-Usage-Limit": "100",
                    "X-Usage-Remaining": "99",
                },
            )
        )
        provider = CompSniperProvider(api_key="cs_test_not_real", enabled=True)
        page = await provider.scrape("Sony A7 IV", ebay_site="ebay.co.uk")
    assert page.ok is True
    assert page.items[0].sold_price == Decimal("1100.00")
    assert page.items[0].sold_currency == "GBP"
    health = await provider.healthcheck()
    assert health["quota_remaining"] == 99
    assert health["rate_limit_remaining"] == 59
    assert health["last_http_status"] == 200
    assert health["status"] == "LIVE"


@pytest.mark.asyncio
async def test_compsniper_quota_exceeded_fail_closed() -> None:
    reset_health_for_tests()
    with respx.mock:
        respx.get("https://api.compsniper.com/v1/scrape").mock(
            return_value=httpx.Response(
                429,
                json={"error": "quota exhausted", "code": "quota_exceeded"},
            )
        )
        provider = CompSniperProvider(api_key="cs_test_not_real", enabled=True)
        page = await provider.scrape("Sony A7 IV")
    assert page.ok is False
    assert page.error_code == "quota_exceeded"
    health = await provider.healthcheck()
    assert health["status"] == "DEGRADED"


def test_sold_date_and_currency_parsers() -> None:
    assert parse_money("1,245.00") == Decimal("1245.00")
    dt = parse_sold_at("2026-08-01")
    assert dt is not None and dt.tzinfo is not None
    iso = parse_sold_at("2026-08-01T12:00:00.000Z")
    assert iso is not None and iso.tzinfo is not None


def test_marketplace_mapping_uk_first() -> None:
    body = camera_by_id("sony|a7-iv|body")
    assert body is not None
    plan = query_plan_for(body)
    assert plan[0]["marketplace"] == "GB"
    assert plan[0]["ebay_site"] == "ebay.co.uk"
    assert plan[1]["ebay_site"] == "ebay.de"
    assert "A7R" in plan[0]["keyword"] or "-A7R" in plan[0]["keyword"]


def test_cache_key_dedupes_listings_of_same_product() -> None:
    a = cache_key("sony|a7-iv|body", "body", "GB", "used")
    b = cache_key("sony|a7-iv|body", "body", "GB", "used")
    c = cache_key("sony|a7-iv|body", "body", "DE", "used")
    assert a == b
    assert a != c
    assert ttl_hours(accepted_count=12) < ttl_hours(accepted_count=1)


def test_condition_parts_not_working() -> None:
    parts = map_sold_condition("For parts or not working", condition_id="7000")
    assert parts.grade == SOLD_PARTS
    assert parts.working is False
    used = map_sold_condition("Pre-Owned", condition_id="3000")
    assert used.grade == SOLD_GOOD
    assert used.working is True


def test_identity_rejects_accessory_wrong_model_kit_parts() -> None:
    body = camera_by_id("sony|a7-iv|body")
    assert validate_camera_sold(target=body, sold_title="Sony A7 IV leather case").accepted is False
    assert validate_camera_sold(target=body, sold_title="Sony A7 IV leather case").reason == "accessory"
    assert validate_camera_sold(target=body, sold_title="Sony A7R IV ILCE-7RM4").accepted is False
    assert validate_camera_sold(target=body, sold_title="Sony A7 III body").accepted is False
    assert validate_camera_sold(target=body, sold_title="Sony A7 IV kit 28-70").accepted is False
    assert validate_camera_sold(target=body, sold_title="Sony A7 IV for parts not working").accepted is False
    assert validate_camera_sold(target=body, sold_title="Sony A7 IV Body Only ILCE-7M4").accepted is True
    assert validate_camera_sold(target=body, sold_title="Sony A7 IV Body Only ILCE-7M4").product_class == "camera_body"


def test_identity_rejects_live_kit_false_accepts() -> None:
    a7iii = camera_by_id("sony|a7-iii|body")
    a7riv = camera_by_id("sony|a7r-iv|body")
    xt5 = camera_by_id("fujifilm|x-t5|body")
    kits = [
        (a7iii, "Sony Alpha a7 III ILCE-7M3 Digital Camera + FE 50mm f/1.8"),
        (a7riv, "Sony A7R IV ILCE-7RM4 Body + FE 1.8/50mm etc"),
        (xt5, "Fujifilm X-T5 + 35mm f/2"),
        (
            camera_by_id("fujifilm|x-t4|body"),
            "Fujifilm X-T4 26.1 MP Mirrorless Camera - Black (with XF 16-80mm f/4 R OIS WR)",
        ),
        (
            a7iii,
            "Sony Alpha A7 III Camera Body with Tamron 28-75mm F2.8 Lens + More!",
        ),
    ]
    for body, title in kits:
        verdict = validate_camera_sold(target=body, sold_title=title)
        assert verdict.accepted is False, title
        assert verdict.reason == "kit_or_bundle", title
    extras = validate_camera_sold(
        target=a7iii, sold_title="Sony A7 III ILCE-7M3 Body Only + extras"
    )
    assert extras.accepted is True
    lens = validate_camera_sold(target=a7iii, sold_title="Sony FE 50mm f/1.8")
    assert lens.accepted is False


def test_r6_ii_keyword_does_not_self_exclude() -> None:
    body = camera_by_id("canon|r6-ii|body")
    assert body is not None
    keyword = body.keyword()
    assert '-"R6 "' not in keyword
    assert "Canon EOS R6 II" in keyword
    assert "-R5" in keyword
    assert "-R7" in keyword


def test_identity_precision_meets_95() -> None:
    result = measure_identity_precision()
    assert result["sample_size"] >= 100
    assert result["exact_match_precision"] >= 0.95
    assert result["accepted_wrong"] == 0
    assert result["pass"] is True


def test_uk_proxy_valuation_not_ireland_premium() -> None:
    now = datetime.now(timezone.utc)
    comps = [
        Comp(
            source="compsniper",
            url=f"https://ebay/{i}",
            title="Sony A7 IV body",
            price_eur=Decimal(str(1200 + i)),
            evidence_type=EvidenceType.REALISED_SALE,
            country="GB",
            condition_score=Decimal("0.9"),
            product_score=Decimal("0.95"),
            observed_at=now - timedelta(days=i),
            evidence_class="A",
        )
        for i in range(8)
    ]
    result = value_from_comps(comps)
    assert result.local_market_method == "UK_REALIZED_PROXY"
    assert result.uk_comp_count == 8
    assert result.value_status == "VALIDATED_VALUE"
    assert result.expected_sale_eur > 0
    assert result.localisation_confidence > 0
    assert "No Ireland premium invented" in result.provenance["localisation"]["note"]
    assert result.local_market_method == "UK_REALIZED_PROXY"


def test_asking_still_not_value() -> None:
    now = datetime.now(timezone.utc)
    comps = [
        Comp(
            source="reverb",
            url="https://x",
            title="Sony A7 IV",
            price_eur=Decimal("1400"),
            evidence_type=EvidenceType.CURRENT_ASKING,
            country="DE",
            condition_score=Decimal("0.8"),
            product_score=Decimal("0.8"),
            observed_at=now,
        )
    ]
    result = value_from_comps(comps)
    assert result.expected_sale_eur == Decimal("0.00")
    assert result.value_status == "UNVALIDATED_VALUE"


def test_stale_evidence_cannot_buy_ready(monkeypatch) -> None:
    from app.decision import gates as gates_mod

    monkeypatch.setattr(gates_mod.settings, "safe_start_mode", True)
    monkeypatch.setattr(gates_mod.settings, "safe_start_max_purchase_eur", "250")
    result = _gates(sold_evidence_fresh=False)
    assert result.money_ready is False
    assert "SOURCE_FRESHNESS_PASS" in result.failures or "PRICE_EVIDENCE_PASS" in result.failures


def test_provider_outage_fail_closed(monkeypatch) -> None:
    from app.decision import gates as gates_mod

    monkeypatch.setattr(gates_mod.settings, "safe_start_mode", True)
    result = _gates(realised_count=0, comparable_count=0, valuation_confidence=Decimal("0.20"), uk_comp_count=0)
    assert result.money_ready is False
    assert result.money_ready_decision == MoneyReadyDecision.REVIEW


def test_uk_proxy_can_pass_localisation(monkeypatch) -> None:
    from app.decision import gates as gates_mod

    monkeypatch.setattr(gates_mod.settings, "safe_start_mode", True)
    monkeypatch.setattr(gates_mod.settings, "safe_start_max_purchase_eur", "250")
    result = _gates()
    assert result.gates["LOCALISATION_PASS"] is True


def test_valuation_anomaly_blocks_buy_ready(monkeypatch) -> None:
    from app.decision import gates as gates_mod

    monkeypatch.setattr(gates_mod.settings, "safe_start_mode", True)
    monkeypatch.setattr(gates_mod.settings, "safe_start_max_purchase_eur", "250")
    result = _gates(valuation_anomaly=True)
    assert result.money_ready is False
    assert "DATA_PROVENANCE_PASS" in result.failures


def test_sanity_band_flags_450_vs_1200() -> None:
    body = camera_by_id("sony|a7-iv|body")
    hit = check_anomaly(body, Decimal("450"))
    assert hit["anomaly"] is True
    miss = check_anomaly(body, Decimal("1250"))
    assert miss["anomaly"] is False


def test_normalize_rejects_active_listing() -> None:
    body = camera_by_id("sony|a7-iv|body")
    item = parse_item(
        {
            "itemId": "9",
            "title": "Sony A7 IV Body Only",
            "listingType": "active",
            "endedAt": "2026-08-01",
            "soldPrice": "1000.00",
            "soldCurrency": "GBP",
            "conditionId": 3000,
        }
    )
    rec = normalize_item(item, target=body, ebay_site="ebay.co.uk", rates={"GBP": Decimal("0.85")})
    assert rec.accepted_for_valuation is False
    assert rec.rejection_reason == "not_completed_sale"


def test_dedupe_fingerprint_is_provider_plus_item() -> None:
    from app.sold.persist import _canonical_fingerprint

    a = _canonical_fingerprint("compsniper", "GB", "123")
    b = _canonical_fingerprint("compsniper", "GB", "123")
    c = _canonical_fingerprint("compsniper", "GB", "124")
    assert a == b
    assert a != c


@pytest.mark.asyncio
async def test_compsniper_disabled_does_not_call_api() -> None:
    reset_health_for_tests()
    with respx.mock:
        route = respx.get("https://api.compsniper.com/v1/scrape").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        provider = CompSniperProvider(api_key="cs_test_not_real", enabled=False)
        page = await provider.scrape("Sony A7 IV")
    assert page.ok is False
    assert page.error_code == "disabled"
    assert route.called is False


@pytest.mark.asyncio
async def test_compsniper_rate_limited_fail_closed() -> None:
    reset_health_for_tests()
    with respx.mock:
        respx.get("https://api.compsniper.com/v1/scrape").mock(
            return_value=httpx.Response(
                429,
                json={"error": "slow down", "code": "rate_limited"},
            )
        )
        provider = CompSniperProvider(api_key="cs_test_not_real", enabled=True)
        page = await provider.scrape("Sony A7 IV")
    assert page.ok is False
    assert page.error_code == "rate_limited"
    health = await provider.healthcheck()
    assert health["status"] == "DEGRADED"


def test_sold_distribution_uses_accepted_tickets_not_provider_median() -> None:
    now = datetime.now(timezone.utc)
    comps = [
        Comp(
            source="compsniper",
            url=f"https://ebay/{price}",
            title="Sony A7 IV body",
            price_eur=Decimal(str(price)),
            evidence_type=EvidenceType.REALISED_SALE,
            country="GB",
            condition_score=Decimal("0.9"),
            product_score=Decimal("0.95"),
            observed_at=now,
            evidence_class="A",
        )
        for price in (900, 1100, 1200, 1250, 1300, 1400, 2500)
    ]
    result = value_from_comps(comps)
    assert result.realised_comp_count >= 3
    assert result.p25 > 0
    assert result.median > result.p25
    assert result.p75 >= result.median
    assert result.method != "provider_median"
    assert result.local_market_method == "UK_REALIZED_PROXY"


def test_liquidity_from_realised_tickets() -> None:
    from app.liquidity.realized import HIGH, liquidity_from_sold

    velocity = {
        "kind": HIGH,
        "sales_count_30d": 10,
        "sales_count_90d": 24,
    }
    result = liquidity_from_sold(velocity, comparable_count=10, is_lot=False)
    assert result.kind == HIGH
    assert result.expected_days_to_sale == 14
    unknown = liquidity_from_sold({"kind": "UNKNOWN", "sales_count_90d": 0}, comparable_count=8, is_lot=False)
    assert unknown.kind == "UNKNOWN"
    assert unknown.expected_days_to_sale is None


def test_lookahead_backtest_is_dated() -> None:
    from app.sold.backtest_sold import synthetic_lookahead_backtest

    result = synthetic_lookahead_backtest()
    assert result["lookahead_free"] is True
    assert Decimal(str(result["mae"])) > 0 or Decimal(str(result["mae"])) == 0
    assert result["train_n"] >= 5
    assert 0 <= result["p25_p75_coverage"] <= 1


def test_camera_body_not_certified_without_live_coverage() -> None:
    from app.sold.certify import camera_body_certification_snapshot
    from app.sold.identity_gate import measure_identity_precision

    snap = camera_body_certification_snapshot(precision=measure_identity_precision())
    assert snap["certified"] is False
    assert any("realised_coverage" in r for r in snap["reasons"])


def test_compsniper_adapter_is_reference_not_acquisition() -> None:
    from app.sources.compsniper import CompSniperAdapter

    adapter = CompSniperAdapter()
    assert adapter.kind.value == "reference"


@pytest.mark.asyncio
async def test_compsniper_adapter_search_returns_no_listings() -> None:
    from app.sources.compsniper import CompSniperAdapter

    items = await CompSniperAdapter().search("Sony A7 IV", limit=5)
    assert items == []


def test_scan_queries_put_exact_cameras_first() -> None:
    from app.pipeline.service import _acquisition_queries
    from app.sold.cameras import CAMERA_BODIES

    queries = _acquisition_queries(None, "scheduler")
    assert queries[0] == CAMERA_BODIES[0].aliases[0]
    assert "Sony A7 IV" in queries
    assert queries[:12] == [body.aliases[0] for body in CAMERA_BODIES]


def test_persist_rejected_and_dedupes() -> None:
    from sqlalchemy import create_engine, select
    from sqlalchemy.dialects.postgresql import JSONB, UUID
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.evidence.providers.compsniper import parse_item
    from app.models.orm import SoldEvidence
    from app.sold.cameras import camera_by_id
    from app.sold.normalize import normalize_item
    from app.sold.persist import persist_canonical_sold

    @compiles(JSONB, "sqlite")
    def _jsonb(type_, compiler, **kw):  # noqa: ARG001
        return "JSON"

    @compiles(UUID, "sqlite")
    def _uuid(type_, compiler, **kw):  # noqa: ARG001
        return "CHAR(36)"

    import app.models.orm  # noqa: F401

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    factory = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    body = camera_by_id("sony|a7-iv|body")
    good = normalize_item(
        parse_item(
            {
                "itemId": "111",
                "url": "https://www.ebay.co.uk/itm/111",
                "title": "Sony A7 IV Body Only ILCE-7M4",
                "listingType": "sold",
                "endedAt": "2026-08-01",
                "soldPrice": "1100.00",
                "soldCurrency": "GBP",
                "conditionId": 3000,
            }
        ),
        target=body,
        ebay_site="ebay.co.uk",
        rates={"GBP": Decimal("0.85")},
    )
    bad = normalize_item(
        parse_item(
            {
                "itemId": "222",
                "url": "https://www.ebay.co.uk/itm/222",
                "title": "Sony A7 IV leather case",
                "listingType": "sold",
                "endedAt": "2026-08-01",
                "soldPrice": "25.00",
                "soldCurrency": "GBP",
                "conditionId": 3000,
            }
        ),
        target=body,
        ebay_site="ebay.co.uk",
        rates={"GBP": Decimal("0.85")},
    )
    with factory() as session:
        first = persist_canonical_sold(session, [good, bad])
        second = persist_canonical_sold(session, [good, bad])
        rows = session.scalars(select(SoldEvidence)).all()
    assert first["imported"] == 2
    assert first["imported_accepted"] == 1
    assert first["rejected"] == 1
    assert second["duplicates"] == 2
    assert len(rows) == 2
    accepted_flags = [row.extras.get("accepted_for_valuation") for row in rows]
    assert True in accepted_flags
    assert False in accepted_flags
    assert any(row.extras.get("rejection_reason") == "accessory" for row in rows)


def test_cache_freshness_ttl() -> None:
    from datetime import timedelta
    from types import SimpleNamespace

    from app.sold.cache import cache_is_fresh, ttl_hours

    now = datetime.now(timezone.utc)
    hot = SimpleNamespace(queried_at=now - timedelta(hours=2), ttl_hours=ttl_hours(accepted_count=12))
    stale = SimpleNamespace(queried_at=now - timedelta(hours=80), ttl_hours=ttl_hours(accepted_count=1))
    assert cache_is_fresh(hot, now=now) is True  # type: ignore[arg-type]
    assert cache_is_fresh(stale, now=now) is False  # type: ignore[arg-type]


def test_api_key_enables_provider_when_flag_defaults_false(monkeypatch) -> None:
    from app.evidence.providers import compsniper as cs

    reset_health_for_tests()
    monkeypatch.setattr(cs.settings, "compsniper_api_key", "cs_test_not_real")
    monkeypatch.setattr(cs.settings, "compsniper_enabled", False)
    assert cs._enabled() is True
    health = cs.compsniper_health()
    assert health["configured"] is True
    assert health["enabled"] is True
    assert health["status"] == "LIVE"


def test_blank_key_stays_disabled(monkeypatch) -> None:
    from app.evidence.providers import compsniper as cs

    reset_health_for_tests()
    monkeypatch.setattr(cs.settings, "compsniper_api_key", "")
    monkeypatch.setattr(cs.settings, "compsniper_enabled", True)
    assert cs._enabled() is False
    health = cs.compsniper_health()
    assert health["enabled"] is False
    assert health["status"] == "BLOCKED_CREDENTIALS"
    assert health["configured"] is False


@pytest.mark.asyncio
async def test_adapter_accepts_snake_case_and_nested_items() -> None:
    reset_health_for_tests()
    payload = {
        "keyword": "Sony A7 IV",
        "data": {
            "items": [
                {
                    "item_id": "555",
                    "itemUrl": "https://www.ebay.co.uk/itm/555",
                    "title": "Sony A7 IV Body Only ILCE-7M4",
                    "listing_type": "buy_it_now",
                    "ended_at": "2026-08-10",
                    "sold_price": "1090.00",
                    "sold_currency": "GBP",
                    "condition_id": 3000,
                    "isBestOfferAccepted": False,
                }
            ]
        },
    }
    with respx.mock:
        respx.get("https://api.compsniper.com/v1/scrape").mock(
            return_value=httpx.Response(200, json=payload)
        )
        page = await CompSniperProvider(api_key="cs_test_not_real", enabled=True).scrape("Sony A7 IV")
    assert page.ok is True
    assert len(page.items) == 1
    assert page.items[0].sold_price == Decimal("1090.00")
    assert page.items[0].listing_type == "buy_it_now"


def test_best_offer_is_upper_bound_not_known_price() -> None:
    body = camera_by_id("sony|a7-iv|body")
    item = parse_item(
        {
            "itemId": "boa-1",
            "title": "Sony A7 IV Body Only ILCE-7M4",
            "listingType": "sold",
            "endedAt": "2026-08-01",
            "soldPrice": "1400.00",
            "soldCurrency": "GBP",
            "conditionId": 3000,
            "bestOfferAccepted": True,
        }
    )
    rec = normalize_item(item, target=body, ebay_site="ebay.co.uk", rates={"GBP": Decimal("0.85")})
    assert rec.price_certainty == "UPPER_BOUND"
    assert rec.accepted_for_valuation is False
    assert rec.rejection_reason == "best_offer_upper_bound"
    known = parse_item(
        {
            "itemId": "bin-1",
            "title": "Sony A7 IV Body Only ILCE-7M4",
            "listingType": "sold",
            "endedAt": "2026-08-01",
            "soldPrice": "1100.00",
            "soldCurrency": "GBP",
            "conditionId": 3000,
            "bestOfferAccepted": False,
        }
    )
    known_rec = normalize_item(known, target=body, ebay_site="ebay.co.uk", rates={"GBP": Decimal("0.85")})
    assert known_rec.accepted_for_valuation is True
    assert known_rec.price_certainty == "KNOWN_TRANSACTION"


def test_buy_it_now_completed_sale_is_not_rejected_as_active() -> None:
    body = camera_by_id("sony|a7-iv|body")
    item = parse_item(
        {
            "itemId": "bin-2",
            "title": "Sony A7 IV Body Only ILCE-7M4",
            "listingType": "buy_it_now",
            "endedAt": "2026-08-01",
            "soldPrice": "1100.00",
            "soldCurrency": "GBP",
            "conditionId": 3000,
        }
    )
    rec = normalize_item(item, target=body, ebay_site="ebay.co.uk", rates={"GBP": Decimal("0.85")})
    assert rec.accepted_for_valuation is True


def test_error_cache_is_not_successful_for_buy_ready() -> None:
    from types import SimpleNamespace

    from app.sold.cache import cache_is_fresh, cache_is_successful

    now = datetime.now(timezone.utc)
    failed = SimpleNamespace(
        queried_at=now - timedelta(hours=1),
        ttl_hours=18,
        last_http_status=429,
        extras={"code": "rate_limited"},
    )
    ok = SimpleNamespace(
        queried_at=now - timedelta(hours=1),
        ttl_hours=18,
        last_http_status=200,
        extras={},
    )
    assert cache_is_fresh(failed, now=now) is True  # type: ignore[arg-type]
    assert cache_is_successful(failed, now=now) is False  # type: ignore[arg-type]
    assert cache_is_successful(ok, now=now) is True  # type: ignore[arg-type]


def test_required_jobs_are_registered() -> None:
    from app.jobs.scheduler import REQUIRED_JOB_IDS

    assert "scan-live-sources" in REQUIRED_JOB_IDS
    assert "sold-evidence-refresh" in REQUIRED_JOB_IDS
    assert "revalue-after-evidence" in REQUIRED_JOB_IDS
    assert "revalue-all-active" in REQUIRED_JOB_IDS


def test_camera_safe_start_is_evidence_not_250_cap(monkeypatch) -> None:
    from app.decision import gates as gates_mod

    monkeypatch.setattr(gates_mod.settings, "safe_start_mode", True)
    monkeypatch.setattr(gates_mod.settings, "safe_start_max_purchase_eur", "250")
    monkeypatch.setattr(gates_mod.settings, "safe_start_camera_max_purchase_eur", "1000")
    monkeypatch.setattr(gates_mod.settings, "safe_start_camera_min_realised", 8)
    monkeypatch.setattr(gates_mod.settings, "max_single_item_loss_eur", "150")
    thin = _gates(
        asking=Decimal("800"),
        purchase_price=Decimal("800"),
        all_in_cost=Decimal("850"),
        product_class="camera_body",
        realised_count=2,
        comparable_count=2,
        liquidity_kind="UNKNOWN",
        p25_sale_eur=Decimal("1200"),
    )
    assert thin.gates["SAFE_START_PASS"] is False
    ready = _gates(
        asking=Decimal("800"),
        purchase_price=Decimal("800"),
        all_in_cost=Decimal("850"),
        expected_profit=Decimal("200"),
        gross_sale=Decimal("1300"),
        net_proceeds=Decimal("1050"),
        downside_profit=Decimal("40"),
        roi=Decimal("0.24"),
        product_class="camera_body",
        realised_count=10,
        comparable_count=10,
        uk_comp_count=10,
        local_market_method="UK_REALIZED_PROXY",
        localisation_confidence=Decimal("0.60"),
        liquidity_kind="HIGH_REALIZED_VELOCITY",
        liquidity_confidence=Decimal("0.70"),
        p25_sale_eur=Decimal("1200"),
        valuation_confidence=Decimal("0.86"),
        max_buy=Decimal("900"),
    )
    assert ready.gates["SAFE_START_PASS"] is True
    over_cap = _gates(
        asking=Decimal("1400"),
        purchase_price=Decimal("1400"),
        all_in_cost=Decimal("1450"),
        expected_profit=Decimal("100"),
        gross_sale=Decimal("1800"),
        net_proceeds=Decimal("1550"),
        product_class="camera_body",
        realised_count=10,
        comparable_count=10,
        liquidity_kind="HIGH_REALIZED_VELOCITY",
        liquidity_confidence=Decimal("0.70"),
        p25_sale_eur=Decimal("1600"),
        valuation_confidence=Decimal("0.86"),
        roi=Decimal("0.24"),
        downside_profit=Decimal("40"),
        max_buy=Decimal("1500"),
    )
    assert over_cap.gates["SAFE_START_PASS"] is False


def test_revalidate_stored_kit_without_provider_call() -> None:
    from sqlalchemy import create_engine, select
    from sqlalchemy.dialects.postgresql import JSONB, UUID
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.evidence.providers.compsniper import parse_item
    from app.models.orm import SoldEvidence
    from app.sold.normalize import normalize_item
    from app.sold.persist import persist_canonical_sold
    from app.sold.refresh import revalidate_stored_sold_evidence

    @compiles(JSONB, "sqlite")
    def _jsonb(type_, compiler, **kw):  # noqa: ARG001
        return "JSON"

    @compiles(UUID, "sqlite")
    def _uuid(type_, compiler, **kw):  # noqa: ARG001
        return "CHAR(36)"

    import app.models.orm  # noqa: F401

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    factory = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    session = factory()
    body = camera_by_id("sony|a7-iii|body")
    raw = {
        "itemId": "kit1",
        "url": "https://www.ebay.co.uk/itm/kit1",
        "title": "Sony Alpha a7 III ILCE-7M3 Digital Camera + FE 50mm f/1.8",
        "listingType": "sold",
        "endedAt": "2026-08-01",
        "soldPrice": "835.00",
        "soldCurrency": "EUR",
        "bestOfferAccepted": False,
        "condition": "Used",
        "conditionId": 3000,
    }
    rec = normalize_item(parse_item(raw), target=body, ebay_site="ebay.co.uk")
    assert rec.accepted_for_valuation is False
    rec.accepted_for_valuation = True
    rec.rejection_reason = ""
    rec.evidence_class = "MARKET_WIDE_COMPLETED_SALE"
    persist_canonical_sold(session, [rec])
    row = session.scalars(select(SoldEvidence)).first()
    assert row.extras["accepted_for_valuation"] is True
    summary = revalidate_stored_sold_evidence(session)
    session.refresh(row)
    assert summary["quota_used"] == 0
    assert summary["flipped_to_reject"] == 1
    assert row.extras["accepted_for_valuation"] is False
    assert row.extras["rejection_reason"] == "kit_or_bundle"
    session.close()


@pytest.mark.asyncio
async def test_ensure_sold_skips_fresh_cache() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.dialects.postgresql import JSONB, UUID
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.sold.cache import upsert_cache
    from app.sold.refresh import ensure_sold_for_listing

    @compiles(JSONB, "sqlite")
    def _jsonb(type_, compiler, **kw):  # noqa: ARG001
        return "JSON"

    @compiles(UUID, "sqlite")
    def _uuid(type_, compiler, **kw):  # noqa: ARG001
        return "CHAR(36)"

    import app.models.orm  # noqa: F401

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    factory = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    session = factory()
    upsert_cache(
        session,
        canonical_product_id="sony|a7-iii|body",
        variant="body",
        marketplace="GB",
        condition_bucket="used",
        keyword="Sony A7 III",
        raw_count=10,
        accepted_count=8,
        rejected_count=2,
        last_http_status=200,
        quota_remaining=80,
    )

    class _Listing:
        brand = "Sony"
        model = "A7 III"
        title = "Sony A7 III body only"

    result = await ensure_sold_for_listing(session, _Listing(), {})  # type: ignore[arg-type]
    assert result["ok"] is True
    assert result["skipped"] == "fresh_cache"
    session.close()


def test_revalue_all_active_does_not_refresh_sold() -> None:
    import inspect

    from app.pipeline.service import revalue_all_active
    from app.sold.refresh import ensure_sold_for_listing, refresh_sold_evidence

    assert "refresh_sold=False" in inspect.getsource(revalue_all_active)
    src = inspect.getsource(ensure_sold_for_listing)
    assert "fresh_cache" in src
    refresh_src = inspect.getsource(refresh_sold_evidence)
    assert "if revalidate:" in refresh_src


@pytest.mark.asyncio
async def test_irish_panel_canonical_query_does_not_miss_older_product() -> None:
    """A global 400-row window dropped older camera tickets and rematched every row."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import create_engine
    from sqlalchemy.dialects.postgresql import JSONB, UUID
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.models.orm import SoldEvidence
    from app.sold.provider import IrishPanelProvider

    @compiles(JSONB, "sqlite")
    def _jsonb(type_, compiler, **kw):  # noqa: ARG001
        return "JSON"

    @compiles(UUID, "sqlite")
    def _uuid(type_, compiler, **kw):  # noqa: ARG001
        return "CHAR(36)"

    import app.models.orm  # noqa: F401

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    factory = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    session = factory()
    now = datetime(2026, 8, 29, tzinfo=timezone.utc)
    filler_title = "Sony Alpha A7 IV Camera Body with Tamron 28-75mm F2.8 Lens + More!"
    for i in range(410):
        session.add(
            SoldEvidence(
                canonical_product_id="sony|a7-iv|body",
                condition="good",
                channel="ebay",
                territory="GB",
                sold_price=Decimal("1500.00"),
                currency="EUR",
                sold_date=now - timedelta(minutes=i),
                source="compsniper",
                evidence_quality="high",
                url_or_reference=f"https://www.ebay.co.uk/itm/filler{i}",
                fingerprint=f"filler{i:04d}" + ("a" * 52),
                extras={
                    "title": filler_title,
                    "accepted_for_valuation": True,
                    "ticket_level": True,
                    "evidence_class": "A",
                    "price_certainty": "KNOWN_TRANSACTION",
                },
            )
        )
    session.add(
        SoldEvidence(
            canonical_product_id="sony|a7-iii|body",
            condition="good",
            channel="ebay",
            territory="GB",
            sold_price=Decimal("699.94"),
            currency="EUR",
            sold_date=now - timedelta(days=20),
            source="compsniper",
            evidence_quality="high",
            url_or_reference="https://www.ebay.co.uk/itm/a7iii-body",
            fingerprint="a7iii-target" + ("b" * 52),
            extras={
                "title": "Sony A7 Mark III ILCE-7M3 Mirrorless Camera Body 42,829 Actuations",
                "accepted_for_valuation": True,
                "ticket_level": True,
                "evidence_class": "A",
                "price_certainty": "KNOWN_TRANSACTION",
            },
        )
    )
    session.flush()
    hits = await IrishPanelProvider(session).search_realised_sales("sony|a7-iii|body", "GB", "good", limit=80)
    assert len(hits) == 1
    assert hits[0].identity_key == "sony|a7-iii|body"
    assert "Tamron" not in hits[0].title
    session.close()


def test_sold_quality_flags_stored_kit_false_accept() -> None:
    from datetime import datetime, timezone

    from sqlalchemy import create_engine
    from sqlalchemy.dialects.postgresql import JSONB, UUID
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.models.orm import SoldEvidence
    from app.sold.quality import sold_quality_report

    @compiles(JSONB, "sqlite")
    def _jsonb(type_, compiler, **kw):  # noqa: ARG001
        return "JSON"

    @compiles(UUID, "sqlite")
    def _uuid(type_, compiler, **kw):  # noqa: ARG001
        return "CHAR(36)"

    import app.models.orm  # noqa: F401

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    factory = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    session = factory()
    session.add(
        SoldEvidence(
            canonical_product_id="sony|a7-iii|body",
            condition="good",
            channel="ebay",
            territory="GB",
            sold_price=Decimal("1509.17"),
            currency="EUR",
            sold_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
            source="compsniper",
            evidence_quality="high",
            url_or_reference="https://www.ebay.co.uk/itm/tamron-kit",
            fingerprint="tamron-kit" + ("c" * 54),
            extras={
                "title": "Sony Alpha A7 III Camera Body with Tamron 28-75mm F2.8 Lens + More!",
                "accepted_for_valuation": True,
                "ticket_level": True,
                "evidence_class": "A",
            },
        )
    )
    session.flush()
    report = sold_quality_report(session)
    model = report["models"]["sony|a7-iii|body"]
    assert model["matcher_false_accept_count"] >= 1
    assert any("Tamron" in row["title"] for row in model["matcher_false_accepts"])
    assert report["totals"]["matcher_false_accepts"] >= 1
    session.close()


def test_uncertified_category_keeps_250_cap(monkeypatch) -> None:
    from app.decision import gates as gates_mod

    monkeypatch.setattr(gates_mod.settings, "safe_start_mode", True)
    result = _gates(
        asking=Decimal("400"),
        purchase_price=Decimal("400"),
        product_class="gpu",
        category="gaming",
    )
    assert result.gates["SAFE_START_PASS"] is False
