"""Owner alerts. Dashboard rows always; Discord/Telegram/email only when configured."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import Decision
from app.models.orm import Alert, Opportunity

logger = get_logger("arie.notifications")


def _should_notify(opp: Opportunity) -> bool:
    if opp.ignored or opp.purchased:
        return False
    return opp.decision in {Decision.BUY.value, "BUY"}


def notify_opportunity(session: Session, opp: Opportunity) -> None:
    """Persist a dashboard alert and fan out to optional channels. Never raises."""
    if not _should_notify(opp):
        return
    title = f"{opp.decision} €{opp.expected_profit_eur}  max buy €{opp.max_buy_eur}"
    body = opp.why or "Opportunity crossed owner thresholds."
    payload = {
        "opportunity_id": str(opp.id),
        "decision": opp.decision,
        "expected_profit_eur": str(opp.expected_profit_eur),
        "expected_roi": str(opp.expected_roi),
        "max_buy_eur": str(opp.max_buy_eur),
        "score": str(opp.score),
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
