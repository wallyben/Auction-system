"""Owner historical sales ingest. High evidence weight, reject malformed rows."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.resolvers import identify_with_resolvers
from app.models.orm import OwnerSale, SoldEvidence

REQUIRED = {"product", "sale_price", "sale_date"}
OPTIONAL = {
    "brand",
    "model",
    "variant",
    "condition",
    "purchase_date",
    "purchase_price",
    "acquisition_source",
    "fees",
    "shipping_in",
    "refurb_cost",
    "sale_platform",
    "listing_price",
    "platform_fee",
    "payment_fee",
    "shipping_out",
    "return_cost",
    "currency",
    "territory",
    "trade_floor",
    "notes",
    "transaction_id",
    "quantity",
    "type",
    "status",
    "refund",
}


def _d(value: str | None) -> Decimal:
    if value is None or str(value).strip() == "":
        return Decimal("0")
    try:
        return Decimal(str(value).replace(",", "").replace("€", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"Invalid money value: {value!r}") from exc


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw[:10], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unparseable date: {value!r}")


def _fp(row: dict[str, str]) -> str:
    key = "|".join(
        [
            (row.get("product") or "").lower(),
            row.get("sale_date") or "",
            row.get("sale_price") or "",
            row.get("sale_platform") or "",
            row.get("transaction_id") or row.get("acquisition_source") or "",
        ]
    )
    return hashlib.sha256(key.encode()).hexdigest()


def parse_owner_sales_csv(text: str) -> tuple[list[dict[str, str]], list[str]]:
    if not text or not text.strip():
        return [], ["Empty file"]
    if "\x00" in text:
        return [], ["Binary/NUL content rejected"]
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return [], ["CSV has no header row"]
    headers = {name.strip().lower().replace(" ", "_") for name in reader.fieldnames if name}
    missing = REQUIRED - headers
    if missing:
        return [], [f"Missing required columns: {sorted(missing)}"]
    rows: list[dict[str, str]] = []
    errors: list[str] = []
    seen_txn: set[str] = set()
    for i, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower().replace(" ", "_"): (v or "").strip() for k, v in raw.items()}
        try:
            if not row.get("product"):
                raise ValueError("product is blank")
            price = _d(row.get("sale_price"))
            if price <= 0:
                raise ValueError("sale_price must be positive")
            sale_date = _date(row.get("sale_date"))
            if sale_date is None:
                raise ValueError("sale_date required")
            cur = (row.get("currency") or "EUR").strip().upper()
            if len(cur) != 3 or not cur.isalpha():
                raise ValueError("currency must be ISO 4217 3-letter code")
            row["currency"] = cur
            qty_raw = row.get("quantity") or "1"
            try:
                qty = int(Decimal(str(qty_raw).replace(",", "")))
            except (InvalidOperation, ValueError) as exc:
                raise ValueError("quantity invalid") from exc
            if qty <= 0:
                raise ValueError("quantity must be positive")
            row["quantity"] = str(qty)
            blob = " ".join(
                [
                    row.get("notes") or "",
                    row.get("type") or "",
                    row.get("transaction_type") or "",
                    row.get("status") or "",
                    row.get("refund") or "",
                ]
            ).lower()
            if (row.get("refund") or "").lower() in {"yes", "true", "1", "y"}:
                raise ValueError("refund_row")
            if re.search(r"\b(refund|refunded|chargeback)\b", blob):
                raise ValueError("refund_row")
            if re.search(r"\b(returned|return to sender)\b", blob) and not re.search(r"\bno returns\b", blob):
                raise ValueError("return_row")
            txn = (row.get("transaction_id") or row.get("acquisition_source") or "").strip()
            if txn:
                if txn in seen_txn:
                    raise ValueError("duplicate transaction_id")
                seen_txn.add(txn)
            _d(row.get("purchase_price") or "0")
            rows.append(row)
        except ValueError as exc:
            errors.append(f"row {i}: {exc}")
    return rows, errors


def import_owner_sales(session: Session, text: str) -> dict[str, int | list[str]]:
    rows, errors = parse_owner_sales_csv(text)
    written = 0
    skipped = 0
    for row in rows:
        fp = _fp(row)
        existing = session.scalar(select(OwnerSale).where(OwnerSale.fingerprint == fp))
        if existing:
            skipped += 1
            continue
        identity = identify_with_resolvers(
            title=row["product"],
            brand_hint=row.get("brand"),
            model_hint=row.get("model"),
            category=None,
        )
        sale = OwnerSale(
            canonical_key=identity.canonical_key,
            product=row["product"],
            brand=row.get("brand") or identity.brand,
            model=row.get("model") or identity.model,
            variant=row.get("variant") or identity.variant,
            condition=row.get("condition") or "unknown",
            purchase_date=_date(row.get("purchase_date")),
            purchase_price=_d(row.get("purchase_price")) if row.get("purchase_price") else None,
            acquisition_source=row.get("acquisition_source"),
            fees=_d(row.get("fees")),
            shipping_in=_d(row.get("shipping_in")),
            refurb_cost=_d(row.get("refurb_cost")),
            sale_platform=row.get("sale_platform"),
            listing_price=_d(row.get("listing_price")) if row.get("listing_price") else None,
            sale_price=_d(row["sale_price"]),
            platform_fee=_d(row.get("platform_fee")),
            payment_fee=_d(row.get("payment_fee")),
            shipping_out=_d(row.get("shipping_out")),
            return_cost=_d(row.get("return_cost")),
            sale_date=_date(row["sale_date"]) or datetime.now(timezone.utc),
            currency=(row.get("currency") or "EUR")[:3].upper(),
            territory=(row.get("territory") or "IE")[:8].upper(),
            notes=row.get("notes") or "",
            fingerprint=fp,
            raw=row,
        )
        session.add(sale)
        session.add(
            SoldEvidence(
                canonical_product_id=identity.canonical_key,
                condition=sale.condition,
                channel=sale.sale_platform or "owner",
                territory=sale.territory or "IE",
                sold_price=sale.sale_price,
                currency=sale.currency or "EUR",
                shipping_charged=sale.shipping_out or None,
                fees_if_known=sale.platform_fee + sale.payment_fee if (sale.platform_fee or sale.payment_fee) else None,
                sold_date=sale.sale_date,
                source="owner_recorded",
                evidence_quality="high",
                url_or_reference=None,
                fingerprint=fp,
                extras={
                    "title": row["product"],
                    "variant": sale.variant,
                    "provenance": "owner_csv",
                    "market": sale.territory,
                    "trade_floor": row.get("trade_floor") or None,
                    "quantity": int(row.get("quantity") or 1),
                    "transaction_id": row.get("transaction_id") or row.get("acquisition_source") or None,
                    "classification": "OWNER_RECORDED",
                    "evidence_class": "C",
                    "ticket_level": True,
                    "market_wide": False,
                    "asking_relabelled": False,
                },
            )
        )
        written += 1
    session.flush()
    return {"imported": written, "duplicates": skipped, "rejected": len(errors), "errors": errors}
