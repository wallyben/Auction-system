"""eBay user-OAuth consent routes. No dashboard auth. Does not bypass MFA."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.sold.ebay_owner_oauth import consent_status, exchange_code, ingest_owner_orders, start_consent
from app.sold.importers import owner_sales_template

router = APIRouter(tags=["ebay-oauth"])


def get_db():
    yield from get_db_session()


@router.get("/oauth/ebay/status")
def ebay_oauth_status(session: Session = Depends(get_db)):
    started = start_consent(session)
    status = consent_status(session)
    return {**status, "consent_url": started.get("consent_url"), "ok": bool(started.get("ok"))}


@router.get("/oauth/ebay/start")
def ebay_oauth_start(session: Session = Depends(get_db)):
    result = start_consent(session)
    if result.get("ok") and result.get("url"):
        return RedirectResponse(result["url"], status_code=302)
    return JSONResponse(result, status_code=400)


@router.get("/oauth/ebay/callback")
async def ebay_oauth_callback(request: Request, session: Session = Depends(get_db)):
    code = request.query_params.get("code") or ""
    state = request.query_params.get("state") or ""
    if not code:
        return JSONResponse({"ok": False, "error": "missing_code"}, status_code=400)
    result = await exchange_code(code, state, session)
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)


@router.post("/sold/ebay/ingest")
async def ebay_sold_ingest(session: Session = Depends(get_db)):
    result = await ingest_owner_orders(session, limit=200)
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)


@router.get("/sold/template")
def sold_template():
    return PlainTextResponse(owner_sales_template(), media_type="text/csv")
