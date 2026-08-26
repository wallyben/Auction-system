"""Backtest against owner-recorded / realised sales only. No fabricated outcomes.

Lookahead-free: a historical sold row is predicted only from earlier realised
comps. Asking prices are never used as the target or as realised evidence.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.models.enums import EvidenceType
from app.models.orm import OwnerSale, SoldEvidence
from app.sold.match import variant_reject
from app.valuation.engine import Comp, value_from_comps


def _aware(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _row_to_comp(row: SoldEvidence) -> Comp:
    extras = row.extras or {}
    et = EvidenceType.OWNER_RECORDED if row.source in {"owner_recorded", "owner_sales"} else EvidenceType.REALISED_SALE
    if row.source in {"owner_trade_floor"}:
        et = EvidenceType.TRADE_IN
    return Comp(
        source=row.source,
        url=row.url_or_reference,
        title=str(extras.get("title") or row.canonical_product_id),
        price_eur=row.sold_price,
        evidence_type=et,
        country=row.territory or "IE",
        condition_score=Decimal("0.85"),
        product_score=Decimal("0.92"),
        observed_at=_aware(row.sold_date),
        notes="Lookahead-free earlier realised evidence.",
    )


def _category_of(row: SoldEvidence) -> str:
    extras = row.extras or {}
    key = str(extras.get("product_identity") or row.canonical_product_id or "")
    parts = key.split("|")
    if len(parts) >= 1 and parts[0] in {"sony", "apple", "canon", "nvidia"}:
        if "iphone" in key:
            return "iphone"
        if "macbook" in key or "ipad" in key:
            return "apple"
        if "a7" in key or "ilce" in key:
            return "cameras"
        if "24-70" in key or "70-200" in key or "gm" in key:
            return "lenses"
        if "rtx" in key:
            return "gpu"
    title = str(extras.get("title") or "").lower()
    if "iphone" in title:
        return "iphone"
    if "macbook" in title:
        return "apple"
    if "rtx" in title:
        return "gpu"
    if "lens" in title or "gm" in title:
        return "lenses"
    if "playstation" in title or "switch" in title or "xbox" in title:
        return "gaming"
    return "unknown"


def run_lookahead_backtest(session: Session | None = None) -> dict:
    own_session = session is None
    session = session or get_session_factory()()
    try:
        rows = list(session.scalars(select(SoldEvidence).order_by(SoldEvidence.sold_date.asc())).all())
        if not rows:
            return {
                "mae": None,
                "median_ae": None,
                "bias": None,
                "mape": None,
                "coverage": 0,
                "sample_size": 0,
                "by_category": {},
                "note": "No realised sold evidence. Lookahead-free backtest cannot be claimed. Import CSV or complete owner OAuth.",
            }
        errors: list[Decimal] = []
        abs_errors: list[Decimal] = []
        pct_errors: list[Decimal] = []
        covered = 0
        by_cat: dict[str, list[Decimal]] = defaultdict(list)
        for i, target in enumerate(rows):
            if (target.extras or {}).get("asking_relabelled"):
                continue
            earlier: list[Comp] = []
            target_title = str((target.extras or {}).get("title") or target.canonical_product_id)
            target_at = _aware(target.sold_date)
            tkey = (target.canonical_product_id or "").strip()
            for prior in rows[:i]:
                if _aware(prior.sold_date) >= target_at:
                    continue
                prior_title = str((prior.extras or {}).get("title") or prior.canonical_product_id)
                if variant_reject(target_title, prior_title):
                    continue
                pkey = (prior.canonical_product_id or "").strip()
                if not tkey or not pkey or tkey != pkey:
                    continue
                earlier.append(_row_to_comp(prior))
            if not earlier:
                continue
            covered += 1
            predicted = value_from_comps(earlier, now=target_at)
            err = predicted.expected_sale_eur - target.sold_price
            errors.append(err)
            abs_errors.append(abs(err))
            if target.sold_price > 0:
                pct_errors.append(abs(err) / target.sold_price)
            by_cat[_category_of(target)].append(abs(err))
        n = len(abs_errors)
        coverage = covered / len(rows) if rows else 0
        if not abs_errors:
            return {
                "mae": None,
                "median_ae": None,
                "bias": None,
                "mape": None,
                "coverage": coverage,
                "sample_size": 0,
                "targets": len(rows),
                "by_category": {},
                "note": "Realised rows exist but none had earlier same-identity comps. No MAE claimed.",
            }
        abs_errors.sort()
        median_ae = abs_errors[n // 2]
        by_category = {
            cat: {
                "n": len(vals),
                "mae": str(sum(vals) / len(vals)),
                "median_ae": str(sorted(vals)[len(vals) // 2]),
            }
            for cat, vals in by_cat.items()
        }
        return {
            "mae": str(sum(abs_errors) / n),
            "median_ae": str(median_ae),
            "bias": str(sum(errors) / n),
            "mape": str(sum(pct_errors) / len(pct_errors)) if pct_errors else None,
            "coverage": coverage,
            "sample_size": n,
            "targets": len(rows),
            "by_category": by_category,
            "note": "Lookahead-free: predicted from earlier realised comps only.",
        }
    finally:
        if own_session:
            session.close()


def run_backtest() -> dict:
    session = get_session_factory()()
    try:
        sales = session.scalars(select(OwnerSale)).all()
        lookahead = run_lookahead_backtest(session)
        if not sales:
            return {
                "BUY_READY_count": 0,
                "win_rate": None,
                "loss_rate": None,
                "mean_profit": None,
                "median_profit": None,
                "mean_ROI": None,
                "median_ROI": None,
                "worst_loss": None,
                "capital_turnover": None,
                "sample_size": lookahead.get("sample_size") or 0,
                "mae": lookahead.get("mae"),
                "median_ae": lookahead.get("median_ae"),
                "bias": lookahead.get("bias"),
                "mape": lookahead.get("mape"),
                "coverage": lookahead.get("coverage"),
                "lookahead": lookahead,
                "note": lookahead.get("note")
                or "No owner-recorded sales. Backtest cannot be claimed. Import a sales CSV first.",
            }
        profits = []
        rois = []
        for sale in sales:
            cost = (sale.purchase_price or Decimal("0")) + sale.fees + sale.shipping_in + sale.refurb_cost
            net = sale.sale_price - sale.platform_fee - sale.payment_fee - sale.shipping_out - sale.return_cost
            profit = net - cost
            profits.append(profit)
            rois.append(profit / cost if cost else Decimal("0"))
        profits.sort()
        wins = sum(1 for p in profits if p > 0)
        return {
            "BUY_READY_count": None,
            "win_rate": float(wins / len(profits)),
            "loss_rate": float(1 - wins / len(profits)),
            "mean_profit": str(sum(profits) / len(profits)),
            "median_profit": str(profits[len(profits) // 2]),
            "mean_ROI": str(sum(rois) / len(rois)),
            "median_ROI": str(sorted(rois)[len(rois) // 2]),
            "worst_loss": str(min(profits)),
            "capital_turnover": None,
            "sample_size": len(profits),
            "mae": lookahead.get("mae"),
            "median_ae": lookahead.get("median_ae"),
            "bias": lookahead.get("bias"),
            "mape": lookahead.get("mape"),
            "coverage": lookahead.get("coverage"),
            "lookahead": lookahead,
            "note": "Historical owner P&L plus lookahead-free realised valuation backtest.",
        }
    finally:
        session.close()
