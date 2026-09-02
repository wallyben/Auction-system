"""eBay user-OAuth consent routes. No dashboard auth. Does not bypass MFA."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.sold.ebay_owner_oauth import consent_status, exchange_code, ingest_owner_orders, start_consent
from app.sold.importers import owner_sales_template
from app.web.offload import isolated_session_async

router = APIRouter(tags=["ebay-oauth"])


def get_db():
    yield from get_db_session()


@router.get("/oauth/ebay/status")
def ebay_oauth_status():
    session = None
    try:
        from app.db.session import get_session_factory

        session = get_session_factory()()
        started = start_consent(session)
        status = consent_status(session)
    except Exception:
        started = start_consent(None)
        status = consent_status(None)
    finally:
        if session is not None:
            session.close()
    return {**status, "consent_url": started.get("consent_url"), "ok": bool(started.get("ok"))}


@router.get("/oauth/ebay/start")
def ebay_oauth_start(session: Session = Depends(get_db)):
    result = start_consent(session)
    if result.get("ok") and result.get("url"):
        return RedirectResponse(result["url"], status_code=302)
    return JSONResponse(result, status_code=400)


@router.get("/oauth/ebay/callback")
async def ebay_oauth_callback(request: Request):
    code = request.query_params.get("code") or ""
    state = request.query_params.get("state") or ""
    if not code:
        return JSONResponse({"ok": False, "error": "missing_code"}, status_code=400)
    # Token exchange + DB persist run on a worker thread so sync SQLAlchemy
    # cannot pin the uvicorn loop. Query-string `code` is never logged.
    result = await asyncio.to_thread(
        isolated_session_async,
        lambda session: exchange_code(code, state, session),
    )
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)


@router.get("/oauth/ebay/declined", response_class=HTMLResponse)
def ebay_oauth_declined():
    return HTMLResponse(
        "<h1>eBay consent declined</h1>"
        "<p>ARIE did not store tokens. Owner sold-order ingestion stays unavailable until you approve "
        "<code>sell.fulfillment.readonly</code>.</p>"
        "<p><a href='/oauth/ebay/start'>Try again</a></p>",
        status_code=200,
    )


@router.get("/privacy/ebay", response_class=HTMLResponse)
def ebay_oauth_privacy():
    return HTMLResponse(
        "<h1>ARIE eBay privacy</h1>"
        "<p>ARIE requests the eBay Production scope <code>sell.fulfillment.readonly</code> so it can ingest "
        "the owner's own sold orders. Refresh tokens are encrypted in Postgres. Token values are never "
        "logged or returned by status endpoints. Active Browse listings are never labelled as sold.</p>"
        "<p>Marketplace Account Deletion notifications are handled at "
        "<code>/webhooks/ebay/account-deletion</code>.</p>",
        status_code=200,
    )


@router.post("/sold/ebay/ingest")
async def ebay_sold_ingest():
    result = await asyncio.to_thread(
        isolated_session_async,
        lambda session: ingest_owner_orders(session, limit=200),
    )
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)


@router.get("/sold/template")
def sold_template():
    return PlainTextResponse(owner_sales_template(), media_type="text/csv")


@router.get("/sold/status")
def sold_status(session: Session = Depends(get_db)):
    from collections import Counter

    from app.models.orm import OwnerSale, SoldEvidence
    from app.sold.token_store import token_status

    rows = session.scalars(select(SoldEvidence).limit(5000)).all()
    owner = session.scalars(select(OwnerSale).limit(5000)).all()
    return {
        "sold_evidence_count": len(rows),
        "owner_sales_count": len(owner),
        "by_source": dict(Counter(r.source for r in rows)),
        "by_market": dict(Counter(r.territory for r in rows)),
        "by_quality": dict(Counter(r.evidence_quality for r in rows)),
        "by_classification": dict(Counter(str((r.extras or {}).get("classification") or r.source) for r in rows)),
        "oauth": token_status(session),
        "secrets_included": False,
    }
