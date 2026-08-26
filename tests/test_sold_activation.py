from decimal import Decimal

from app.comps.matcher import match_comp
from app.condition.match import condition_match_score
from app.sold.crypto import decrypt_secret, encrypt_secret
from app.sold.match import variant_reject
from app.sold.owner import parse_owner_sales_csv


def test_encrypt_roundtrip_and_plaintext_passthrough() -> None:
    token = "refresh-token-secret-value"
    enc = encrypt_secret(token)
    assert enc is not None
    assert enc.startswith("ENC1:")
    assert token not in enc
    assert decrypt_secret(enc) == token
    assert decrypt_secret("plain-legacy") == "plain-legacy"


def test_variant_rejects_iphone_pro_max_and_storage() -> None:
    assert variant_reject("iPhone 15 Pro 256GB", "iPhone 15 Pro Max 256GB") == "iphone_pro_max_mismatch"
    assert variant_reject("iPhone 15 Pro 256GB", "iPhone 15 Pro 128GB") == "storage_mismatch"
    assert variant_reject("iPhone 15 Pro 256GB", "iPhone 14 Pro 256GB") == "wrong_iphone_generation"


def test_variant_rejects_macbook_chip_size_and_memory() -> None:
    assert variant_reject("MacBook Pro 14 M3 Pro 18/512", "MacBook Pro 14 M3 8/512") == "mac_chip_mismatch"
    assert variant_reject("MacBook Pro 14 M3 Pro 18/512", "MacBook Pro 16 M3 Pro 18/512") == "mac_size_mismatch"
    assert variant_reject("MacBook Pro 14 M3 Pro 18/512", "MacBook Pro 14 M3 Pro 8/512") == "mac_memory_mismatch"


def test_variant_rejects_gpu_super_ti_laptop_and_desktop() -> None:
    assert variant_reject("RTX 4070 12GB", "RTX 4070 SUPER 12GB") in {"gpu_super_mismatch", "4070_super_mismatch"}
    assert variant_reject("RTX 4070", "RTX 4070 Ti") == "4070_ti_mismatch"
    assert variant_reject("RTX 4070", "RTX 4070 laptop GPU") in {"accessory", "not_desktop_gpu"}
    assert variant_reject("RTX 4070", "Gaming PC tower RTX 4070") in {"not_desktop_gpu", "gpu_in_desktop"}


def test_variant_rejects_gm_generations_and_focal() -> None:
    assert variant_reject("Sony FE 24-70 GM", "Sony FE 24-70 GM II")
    assert variant_reject("Sony FE 24-70 GM II", "Sony FE 70-200 GM II") == "wrong_focal_length"


def test_match_comp_uses_variant_reject() -> None:
    result = match_comp("iPhone 15 Pro 256GB", "iPhone 15 Pro Max 256GB")
    assert result.accepted is False


def test_condition_match_parts_vs_used_is_zero() -> None:
    score = condition_match_score("Used", "For parts or not working", subject_condition_id="3000", comp_condition_id="7000")
    assert score == Decimal("0")


def test_condition_match_same_used_is_full() -> None:
    score = condition_match_score("Used", "Used", subject_condition_id="3000", comp_condition_id="3000")
    assert score == Decimal("1.00")


def test_csv_rejects_refund_return_qty_and_duplicate_txn() -> None:
    refund = "product,sale_price,sale_date,type\nSony A7 IV,1100,2026-01-15,Refund\n"
    rows, errors = parse_owner_sales_csv(refund)
    assert rows == []
    assert any("refund" in e for e in errors)

    qty = "product,sale_price,sale_date,quantity\nSony A7 IV,1100,2026-01-15,0\n"
    rows, errors = parse_owner_sales_csv(qty)
    assert rows == []
    assert any("quantity" in e for e in errors)

    dup = (
        "product,sale_price,sale_date,transaction_id\n"
        "Sony A7 IV,1100,2026-01-15,TX-1\n"
        "Sony A7 IV,900,2026-02-01,TX-1\n"
    )
    rows, errors = parse_owner_sales_csv(dup)
    assert len(rows) == 1
    assert any("duplicate transaction_id" in e for e in errors)


def test_csv_rejects_bad_currency() -> None:
    csv = "product,sale_price,sale_date,currency\nSony A7 IV,1100,2026-01-15,EURO\n"
    rows, errors = parse_owner_sales_csv(csv)
    assert rows == []
    assert any("currency" in e for e in errors)


def test_parse_orders_skips_cancelled_and_refunded() -> None:
    from app.models.enums import EvidenceType
    from app.sold.ebay_owner_oauth import _parse_orders

    payload = {
        "orders": [
            {
                "orderId": "C1",
                "cancelStatus": {"cancelState": "CANCELED"},
                "creationDate": "2026-01-01T00:00:00Z",
                "lineItems": [{"title": "Sony A7 IV", "lineItemCost": {"value": "1000", "currency": "EUR"}, "lineItemId": "1"}],
            },
            {
                "orderId": "R1",
                "creationDate": "2026-01-02T00:00:00Z",
                "paymentSummary": {"refunds": [{"amount": {"value": "10"}}]},
                "lineItems": [{"title": "Sony A7 IV", "lineItemCost": {"value": "1000", "currency": "EUR"}, "lineItemId": "2"}],
            },
            {
                "orderId": "OK1",
                "creationDate": "2026-01-03T00:00:00Z",
                "lineItems": [
                    {
                        "title": "Sony A7 IV body",
                        "lineItemCost": {"value": "1100", "currency": "EUR"},
                        "lineItemId": "3",
                        "quantity": 1,
                    }
                ],
            },
        ]
    }
    hits = _parse_orders(payload, market="IE")
    assert len(hits) == 1
    assert hits[0].source == "ebay_owner_orders"
    assert hits[0].evidence_type == EvidenceType.REALISED_SALE
    assert hits[0].quantity == 1


def test_oauth_status_route_has_no_secrets() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/oauth/ebay/status")
        declined = client.get("/oauth/ebay/declined")
        privacy = client.get("/privacy/ebay")
        template = client.get("/sold/template")
    assert response.status_code == 200
    body = response.json()
    assert body.get("secrets_included") is False
    assert "access_token" not in body
    assert "refresh_token" not in body or isinstance(body.get("refresh_token_configured"), bool)
    assert declined.status_code == 200
    assert privacy.status_code == 200
    assert template.status_code == 200
    assert "sale_price" in template.text


def test_start_consent_rejects_url_runame(monkeypatch) -> None:
    from app.core.config import get_settings
    from app.sold.ebay_owner_oauth import start_consent

    monkeypatch.setenv("EBAY_CLIENT_ID", "PRD-fake-client")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "PRD-fake-secret")
    monkeypatch.setenv("EBAY_RU_NAME", "https://auction-system-l6je.onrender.com/oauth/ebay/callback")
    get_settings.cache_clear()
    started = start_consent()
    assert started["ok"] is False
    assert started["error"] == "ru_name_must_be_identifier_not_url"
    assert started.get("url") is None
    monkeypatch.delenv("EBAY_RU_NAME", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)
    get_settings.cache_clear()


def test_start_consent_builds_production_authorize_url(monkeypatch) -> None:
    from urllib.parse import parse_qs, urlparse

    from app.core.config import get_settings
    from app.sold.ebay_owner_oauth import OWNER_SOLD_SCOPE, start_consent

    monkeypatch.setenv("EBAY_CLIENT_ID", "PRD-fake-client")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "PRD-fake-secret")
    monkeypatch.setenv("EBAY_RU_NAME", "ARIE-ARIE-PRD-xxxxx-yyyyy")
    get_settings.cache_clear()
    started = start_consent()
    assert started["ok"] is True
    url = started["url"]
    assert url.startswith("https://auth.ebay.com/oauth2/authorize")
    assert "sandbox" not in url
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert query["redirect_uri"] == ["ARIE-ARIE-PRD-xxxxx-yyyyy"]
    assert query["scope"] == [OWNER_SOLD_SCOPE]
    assert query.get("state")
    assert query["response_type"] == ["code"]
    assert "client_secret" not in url
    assert started.get("secrets_included") is False
    monkeypatch.delenv("EBAY_RU_NAME", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)
    get_settings.cache_clear()


def test_refurbished_open_box_new_and_parts_condition() -> None:
    from app.condition.engine import assess_condition
    from app.models.enums import ConditionGrade

    refurb = assess_condition("Certified Refurbished", condition_id="2010")
    assert refurb.grade == ConditionGrade.EXCELLENT
    open_box = assess_condition("Open Box", condition_id="1500")
    assert open_box.grade == ConditionGrade.OPEN_BOX
    new = assess_condition("New", condition_id="1000")
    assert new.grade == ConditionGrade.NEW
    parts = assess_condition("Used", "please read for parts not working", condition_id="3000")
    assert parts.grade == ConditionGrade.FOR_PARTS
    damaged = assess_condition("Used", "cracked screen damaged", condition_id="3000")
    assert damaged.grade == ConditionGrade.POOR
    batt = assess_condition("Used", "battery health 65%", condition_id="3000")
    assert batt.grade == ConditionGrade.FAIR


def test_lookahead_backtest_empty_is_honest() -> None:
    from app.validation.backtest import run_lookahead_backtest

    class _Empty:
        def scalars(self, _stmt):
            class _R:
                def all(self):
                    return []

            return _R()

    result = run_lookahead_backtest(_Empty())  # type: ignore[arg-type]
    assert result["sample_size"] == 0
    assert result["mae"] is None
    assert "cannot be claimed" in result["note"]
