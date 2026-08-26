"""Owner alerts. Dashboard rows always; Discord/Telegram/email only when configured."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import Decision
from app.models.orm import Alert, Listing, Opportunity

logger = get_logger("arie.notifications")


def _should_notify(opp: Opportunity) -> bool:
    if opp.ignored or opp.purchased:
        return False
    wanted = (settings.alert_on or "BUY_READY").upper()
    money = getattr(opp, "money_ready_decision", None) or ""
    if wanted == "BUY_READY":
        return bool(getattr(opp, "money_ready", False) or money == "BUY_READY")
    return opp.decision in {Decision.BUY.value, "BUY"} or money == wanted


def notify_opportunity(session: Session, opp: Opportunity) -> None:
    """Persist a dashboard alert and fan out to optional channels. Never raises."""
    if not _should_notify(opp):
        return
    listing = session.get(Listing, opp.listing_id)
    if listing and listing.source_id == "ebay_browse" and settings.ebay_api_env == "sandbox":
        return
    title = f"BUY_READY {listing.title[:80] if listing else opp.decision}"
    body = (
        f"item={listing.title if listing else ''} source={listing.source_id if listing else ''} "
        f"country={listing.country if listing else ''} ask={listing.asking_price if listing else ''} "
        f"ideal={opp.ideal_offer_eur} max_buy={opp.max_buy_eur} expected_sale={opp.expected_resale_eur} "
        f"best_exit={opp.best_exit_channel} profit={opp.expected_profit_eur} roi={opp.expected_roi} "
        f"days={opp.expected_days_to_sale} confidence={opp.valuation_confidence} "
        f"url={listing.url if listing else ''}"
    )
    payload = {
        "opportunity_id": str(opp.id),
        "item": listing.title if listing else None,
        "source": listing.source_id if listing else None,
        "country": listing.country if listing else None,
        "ask": str(listing.asking_price) if listing and listing.asking_price is not None else None,
        "current_bid": str(listing.current_bid) if listing and listing.current_bid is not None else None,
        "ideal_offer": str(opp.ideal_offer_eur),
        "max_buy": str(opp.max_buy_eur),
        "expected_sale": str(opp.expected_resale_eur),
        "quick_sale": None,
        "best_exit": opp.best_exit_channel,
        "profit": str(opp.expected_profit_eur),
        "roi": str(opp.expected_roi),
        "days": opp.expected_days_to_sale,
        "confidence": str(opp.valuation_confidence),
        "risk": opp.risks,
        "url": listing.url if listing else None,
        "sandbox": False,
    }
    alert = Alert(
        opportunity_id=opp.id,
        channel="dashboard",
        title=title[:256],
        body=body,
        payload=payload,
        delivered=True,
        delivered_at=datetime.now(timezone.utc),
    )
    session.add(alert)
    try:
        if settings.discord_webhook_url:
            _post_json(settings.discord_webhook_url, {"content": f"ARIE {title}\n{body[:1500]}"})
            _extra(session, opp, "discord", title, body, payload)
        if settings.telegram_bot_token and settings.telegram_chat_id:
            url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
            _post_json(url, {"chat_id": settings.telegram_chat_id, "text": f"ARIE {title}\n{body[:1500]}"})
            _extra(session, opp, "telegram", title, body, payload)
    except Exception:
        logger.exception("notify_fanout_failed", opportunity_id=str(opp.id))


def _extra(session: Session, opp: Opportunity, channel: str, title: str, body: str, payload: dict) -> None:
    session.add(
        Alert(
            opportunity_id=opp.id,
            channel=channel,
            title=title[:256],
            body=body,
            payload=payload,
            delivered=True,
            delivered_at=datetime.now(timezone.utc),
        )
    )


def _post_json(url: str, payload: dict) -> None:
    import httpx

    with httpx.Client(timeout=8.0) as client:
        client.post(url, json=payload)


notify_opportunity = notify_opportunity
