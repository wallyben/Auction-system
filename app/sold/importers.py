"""Marketplace sales-history importers. Detect eBay / PayPal / generic CSV headers."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from app.sold.owner import import_owner_sales, parse_owner_sales_csv

TEMPLATE_PATH = Path("docs/data/OWNER_SALES_TEMPLATE.csv")

TEMPLATE_CSV = (
    "product,sale_price,sale_date,currency,territory,brand,model,variant,condition,"
    "sale_platform,shipping_out,platform_fee,payment_fee,trade_floor\n"
    "Sony A7 IV body,1100.00,2026-01-15,EUR,IE,Sony,A7 IV,,used,ebay_ie,12.00,142.00,21.00,\n"
    "Apple iPhone 15 Pro 256GB,720.00,2026-02-02,EUR,IE,Apple,iPhone 15 Pro,256GB,used,ebay_ie,8.00,93.00,14.00,\n"
)

CANONICAL = {
    "product": {
        "product",
        "item title",
        "item_title",
        "title",
        "item name",
        "item_name",
        "listing title",
        "name",
        "subject",
        "item",
        "description",
    },
    "sale_price": {
        "sale_price",
        "sale price",
        "sold for",
        "sold_for",
        "total price",
        "total_price",
        "item price",
        "item_price",
        "gross",
        "amount",
        "net amount",
        "price",
        "sold price",
        "sold_price",
        "total",
        "proceeds",
    },
    "sale_date": {
        "sale_date",
        "sale date",
        "sold on",
        "sold_on",
        "paid on",
        "paid_on",
        "date",
        "date sold",
        "date_sold",
        "end date",
        "end_date",
        "transaction date",
        "date of transaction",
    },
    "currency": {"currency", "curr", "ccy"},
    "territory": {"territory", "site", "marketplace", "ship country", "country", "sold on site"},
    "brand": {"brand"},
    "model": {"model", "custom label", "custom_label"},
    "variant": {"variant", "storage", "colour", "color"},
    "condition": {"condition"},
    "sale_platform": {"sale_platform", "platform", "channel", "sold via"},
    "shipping_out": {
        "shipping_out",
        "postage",
        "shipping and handling",
        "shipping",
        "postage and packaging",
        "delivery",
    },
    "platform_fee": {"platform_fee", "final value fee", "fvf", "fee", "commission"},
    "payment_fee": {"payment_fee", "paypal fee", "transaction fee"},
    "trade_floor": {"trade_floor", "trade in", "trade-in", "cex", "liquidation_floor"},
    "acquisition_source": {"acquisition_source"},
    "transaction_id": {
        "transaction_id",
        "transaction id",
        "txn id",
        "order id",
        "order_id",
        "item number",
        "item id",
        "item_id",
        "paypal transaction id",
    },
    "quantity": {"quantity", "qty", "units"},
    "type": {"type", "transaction type", "transaction_type"},
    "status": {"status"},
    "refund": {"refund", "refunded"},
}


def owner_sales_template() -> str:
    if TEMPLATE_PATH.exists():
        return TEMPLATE_PATH.read_text(encoding="utf-8")
    return TEMPLATE_CSV


def _norm_header(name: str) -> str:
    return " ".join((name or "").replace("\ufeff", "").strip().lower().replace("_", " ").split())


def detect_kind(text: str) -> str:
    sample = text[:800].lower()
    if "final value fee" in sample or "item number" in sample or "sold for" in sample or "item title" in sample:
        return "ebay"
    if "paypal" in sample or ("gross" in sample and "fee" in sample and "date" in sample):
        return "paypal"
    return "generic"


def _sniff_dialect(text: str) -> csv.Dialect:
    sample = text[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        class _Comma(csv.excel):
            delimiter = ","

        return _Comma()


def remap_headers(fieldnames: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for raw in fieldnames:
        norm = _norm_header(raw)
        mapped = None
        for dest, aliases in CANONICAL.items():
            if dest in used:
                continue
            if norm in aliases or norm.replace(" ", "_") in {a.replace(" ", "_") for a in aliases}:
                mapped = dest
                break
        if mapped:
            mapping[raw] = mapped
            used.add(mapped)
        else:
            mapping[raw] = norm.replace(" ", "_")
    return mapping


def normalize_sales_csv(text: str) -> str:
    text = (text or "").replace("\ufeff", "")
    if not text.strip():
        return text
    dialect = _sniff_dialect(text)
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        return text
    mapping = remap_headers([name for name in reader.fieldnames if name])
    out = io.StringIO()
    dest_fields = []
    seen = set()
    for raw in reader.fieldnames:
        dest = mapping.get(raw) or raw
        if dest in seen:
            continue
        seen.add(dest)
        dest_fields.append(dest)
    writer = csv.DictWriter(out, fieldnames=dest_fields, lineterminator="\n")
    writer.writeheader()
    for row in reader:
        written = {mapping.get(k, k): (v or "").strip() for k, v in row.items() if k}
        writer.writerow({k: written.get(k, "") for k in dest_fields})
    return out.getvalue()


def import_marketplace_export(session, text: str, *, kind: str = "auto") -> dict[str, int | list[str]]:
    detected = detect_kind(text) if kind == "auto" else kind
    remapped = normalize_sales_csv(text)
    rows, errors = parse_owner_sales_csv(remapped)
    if errors and not rows:
        return {
            "imported": 0,
            "duplicates": 0,
            "rejected": len(errors),
            "errors": errors,
            "detected_format": detected,
        }
    result = import_owner_sales(session, remapped)
    result["detected_format"] = detected
    return result
