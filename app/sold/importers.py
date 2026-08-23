"""Marketplace sales-history importers. Owner uploads native exports; we map columns."""

from __future__ import annotations

from app.sold.owner import import_owner_sales, parse_owner_sales_csv

# Common header aliases from seller-hub / payout exports.
EBAY_MAP = {
    "item title": "product",
    "title": "product",
    "sold for": "sale_price",
    "sale price": "sale_price",
    "total price": "sale_price",
    "sold on": "sale_date",
    "sale date": "sale_date",
    "paid on": "sale_date",
    "final value fee": "platform_fee",
    "postage": "shipping_out",
    "shipping and handling": "shipping_out",
    "item number": "acquisition_source",
}
PAYPAL_MAP = {
    "name": "product",
    "item title": "product",
    "gross": "sale_price",
    "fee": "payment_fee",
    "date": "sale_date",
}


def _remap(text: str, mapping: dict[str, str]) -> str:
    lines = text.splitlines()
    if not lines:
        return text
    header = lines[0]
    lowered = header.lower()
    for src, dest in mapping.items():
        if src in lowered:
            lowered = lowered.replace(src, dest)
    lines[0] = lowered
    return "\n".join(lines)


def import_marketplace_export(session, text: str, *, kind: str = "auto") -> dict[str, int | list[str]]:
    sample = text[:400].lower()
    if kind == "ebay" or "final value fee" in sample or "item number" in sample:
        text = _remap(text, EBAY_MAP)
    elif kind == "paypal" or "paypal" in sample or "gross" in sample and "fee" in sample:
        text = _remap(text, PAYPAL_MAP)
    rows, errors = parse_owner_sales_csv(text)
    if errors and not rows:
        return {"imported": 0, "duplicates": 0, "rejected": len(errors), "errors": errors}
    return import_owner_sales(session, text)
