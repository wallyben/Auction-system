from decimal import Decimal

from app.exits.engine import compare_exits
from app.exits.fees import fee_for
from app.shipping.engine import estimate_outbound


def test_exit_channels_are_not_a_single_fee() -> None:
    result = compare_exits(expected_sale_eur=Decimal("1000"), category="cameras")
    fees = {q.channel: q.expected_fee for q in result.quotes}
    assert "ebay_ie" in fees
    assert "local_ie" in fees
    assert fees["local_ie"] < fees["ebay_ie"]
    assert result.best_expected_exit


def test_cardmarket_fee_is_not_ebay_default() -> None:
    assert fee_for("cardmarket").percent != fee_for("ebay_ie").percent


def test_shipping_is_not_blind_9_50() -> None:
    cards = estimate_outbound(category="trading_cards", channel="ebay_ie")
    decks = estimate_outbound(category="music_dj", channel="ebay_ie")
    local = estimate_outbound(category="cameras", channel="local_ie")
    assert cards.amount_eur != decks.amount_eur
    assert local.amount_eur < decks.amount_eur
