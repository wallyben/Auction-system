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
