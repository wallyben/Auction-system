"""Backtest against owner-recorded sales only. No fabricated outcomes."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.db.session import get_session_factory
from app.models.orm import OwnerSale


def run_backtest() -> dict:
    session = get_session_factory()()
    try:
        sales = session.scalars(select(OwnerSale)).all()
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
                "sample_size": 0,
                "note": "No owner-recorded sales. Backtest cannot be claimed. Import a sales CSV first.",
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
            "note": "Historical owner P&L only. Not a lookahead-free BUY_READY simulation unless decisions were recorded.",
        }
    finally:
        session.close()
