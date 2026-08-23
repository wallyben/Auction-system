"""Owner purchase → inventory → resale feedback loop."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.money import money
from app.models.enums import InventoryState, LossClass
from app.models.orm import InventoryItem, Listing, LossPostmortem, Opportunity, Outcome, Purchase, Sale


def mark_purchased(
    session: Session,
    opportunity: Opportunity,
    *,
    actual_purchase_price: Decimal,
    actual_shipping: Decimal = Decimal("0"),
    actual_buyer_fee: Decimal = Decimal("0"),
    payment_fee: Decimal = Decimal("0"),
    notes: str = "",
) -> InventoryItem:
    listing = session.get(Listing, opportunity.listing_id)
    now = datetime.now(timezone.utc)
    purchase = Purchase(
        opportunity_id=opportunity.id,
        listing_id=opportunity.listing_id,
        purchased_at=now,
        purchase_price=actual_purchase_price,
        fees=actual_buyer_fee,
        shipping=actual_shipping,
        notes=notes,
        state=InventoryState.PURCHASED.value,
    )
    session.add(purchase)
    session.flush()
    capital = money(actual_purchase_price + actual_shipping + actual_buyer_fee + payment_fee)
    item = InventoryItem(
        opportunity_id=opportunity.id,
        listing_id=opportunity.listing_id,
        purchase_id=purchase.id,
        title=listing.title if listing else "Unknown",
        category=listing.category if listing else None,
        state=InventoryState.PURCHASED.value,
        actual_purchase_price=actual_purchase_price,
        actual_shipping=actual_shipping,
        actual_buyer_fee=actual_buyer_fee,
        payment_fee=payment_fee,
        capital_tied_eur=capital,
        expected_profit_eur=opportunity.expected_profit_eur,
        recommended_list_price=opportunity.expected_resale_eur,
        minimum_accept_price=opportunity.max_buy_eur,
        quick_sale_price=None,
        where_to_list=opportunity.best_exit_channel,
        purchased_at=now,
        notes=notes,
    )
    rec = resale_recommendation(opportunity)
    item.recommended_list_price = rec["recommended_list_price"]
    item.minimum_accept_price = rec["minimum_accept_price"]
    item.quick_sale_price = rec["quick_sale_price"]
    item.where_to_list = rec["where_to_list"]
    session.add(item)
    opportunity.purchased = True
    session.flush()
    return item


def resale_recommendation(opportunity: Opportunity) -> dict:
    expected = opportunity.expected_resale_eur
    return {
        "where_to_list": opportunity.best_exit_channel or "ebay_ie",
        "recommended_list_price": money(expected),
        "minimum_accept_price": money(expected * Decimal("0.90")),
        "quick_sale_price": money(expected * Decimal("0.88")),
    }


def mark_sold(
    session: Session,
    item: InventoryItem,
    *,
    sold_date: datetime,
    sale_price: Decimal,
    sale_channel: str,
    fees: Decimal = Decimal("0"),
    shipping: Decimal = Decimal("0"),
    refunds: Decimal = Decimal("0"),
) -> Sale:
    if item.purchase_id is None:
        raise ValueError("Inventory item has no purchase")
    days = (sold_date - item.purchased_at).days
    actual_net = money(sale_price - fees - shipping - refunds - item.capital_tied_eur)
    sale = Sale(
        purchase_id=item.purchase_id,
        sold_at=sold_date,
        sale_price=sale_price,
        fees=fees,
        shipping=shipping,
        days_to_sale=days,
        channel=sale_channel,
        notes=f"actual_net_profit={actual_net}",
    )
    session.add(sale)
    session.flush()
    item.state = InventoryState.SOLD.value
    session.add(
        Outcome(
            purchase_id=item.purchase_id,
            sale_id=sale.id,
            predicted_resale=item.recommended_list_price,
            actual_resale=sale_price,
            predicted_profit=item.expected_profit_eur,
            actual_profit=actual_net,
            predicted_days=None,
            actual_days=days,
            predicted_cost=item.capital_tied_eur,
            actual_cost=item.capital_tied_eur,
            valuation_error=money((item.recommended_list_price or Decimal("0")) - sale_price),
            profit_error=money((item.expected_profit_eur or Decimal("0")) - actual_net),
            days_error=None,
            cost_error=Decimal("0"),
        )
    )
    if actual_net < 0:
        session.add(
            LossPostmortem(
                inventory_id=item.id,
                purchase_id=item.purchase_id,
                loss_class=LossClass.VALUATION_ERROR.value,
                predicted_profit=item.expected_profit_eur,
                actual_profit=actual_net,
                notes="Auto-opened. Owner should reclassify.",
            )
        )
    session.flush()
    return sale


def run_labelled_test_loop(session: Session, opportunity: Opportunity) -> dict:
    """Exercise purchase → inventory → listed → sold → outcome. Labelled TEST only."""
    item = mark_purchased(
        session,
        opportunity,
        actual_purchase_price=opportunity.all_in_acquisition_eur or opportunity.max_buy_eur,
        actual_shipping=Decimal("8.00"),
        notes="TEST_TRANSACTION — not an owner purchase.",
    )
    item.notes = "TEST_TRANSACTION — not an owner purchase."
    item.state = InventoryState.LISTED.value
    sale = mark_sold(
        session,
        item,
        sold_date=datetime.now(timezone.utc),
        sale_price=opportunity.expected_resale_eur or Decimal("1"),
        sale_channel="test_loop",
        fees=Decimal("1.00"),
        shipping=Decimal("6.00"),
    )
    return {
        "label": "TEST_TRANSACTION",
        "inventory_id": str(item.id),
        "sale_id": str(sale.id),
        "state": item.state,
        "note": "Synthetic loop for software proof. Not a real owner buy/sell.",
    }
