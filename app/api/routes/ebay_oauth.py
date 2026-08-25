"""eBay user-OAuth consent routes. No dashboard auth. Does not bypass MFA."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.sold.ebay_owner_oauth import exchange_code, start_consent

router = APIRouter(tags=["ebay-oauth"])


@router.get("/oauth/ebay/start")
def ebay_oauth_start():
    result = start_consent()
    if result.get("ok") and result.get("url"):
        return RedirectResponse(result["url"], status_code=302)
    return JSONResponse(result, status_code=400)


@router.get("/oauth/ebay/callback")
async def ebay_oauth_callback(request: Request):
    code = request.query_params.get("code") or ""
    state = request.query_params.get("state") or ""
    if not code:
        return JSONResponse({"ok": False, "error": "missing_code"}, status_code=400)
    result = await exchange_code(code, state)
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)
