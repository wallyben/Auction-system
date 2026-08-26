from app.sold.owner import parse_owner_sales_csv


def test_owner_sales_require_columns() -> None:
    rows, errors = parse_owner_sales_csv("foo,bar\n1,2\n")
    assert rows == []
    assert errors


def test_owner_sales_reject_bad_price() -> None:
    csv = "product,sale_price,sale_date\nSony A7 IV,not-a-price,2026-01-01\n"
    rows, errors = parse_owner_sales_csv(csv)
    assert rows == []
    assert any("sale_price" in e or "Invalid" in e for e in errors)


def test_owner_sales_accept_valid_row() -> None:
    csv = "product,sale_price,sale_date,brand,model\nSony A7 IV,1100,2026-01-15,Sony,A7 IV\n"
    rows, errors = parse_owner_sales_csv(csv)
    assert errors == []
    assert len(rows) == 1
    assert rows[0]["product"] == "Sony A7 IV"


def test_ebay_seller_hub_headers_autodetect() -> None:
    from app.sold.importers import detect_kind, normalize_sales_csv

    raw = "Item title,Sold for,Sold on,Item number\nSony A7 IV,1100.00,15/01/2026,123\n"
    assert detect_kind(raw) == "ebay"
    remapped = normalize_sales_csv(raw)
    rows, errors = parse_owner_sales_csv(remapped)
    assert errors == []
    assert rows[0]["product"] == "Sony A7 IV"
    assert rows[0]["sale_price"] == "1100.00"


def test_paypal_headers_autodetect() -> None:
    from app.sold.importers import detect_kind, normalize_sales_csv

    raw = "Name,Gross,Date,Fee\nShure SM7B,240.00,2026-04-01,5.00\n"
    assert detect_kind(raw) == "paypal"
    remapped = normalize_sales_csv(raw)
    rows, errors = parse_owner_sales_csv(remapped)
    assert errors == []
    assert rows[0]["product"] == "Shure SM7B"
