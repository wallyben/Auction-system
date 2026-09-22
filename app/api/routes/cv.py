"""ARIE-CV owner surface. It does not bid, buy, or pay."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.domains.vehicles.board import remember, view
from app.domains.vehicles.evaluate import evaluate_vehicle
from app.domains.vehicles.policy import TAX_RULE_VERSION, TAX_RULES_RETRIEVED_AT
from app.domains.vehicles.present import case_from_payload
from app.domains.vehicles.sources import enabled_live_fetchers, vehicle_sources

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


def _page(request: Request, *, active: str, evaluation: dict | None = None, error: str | None = None) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "cv_dashboard.html",
        {
            "active": active,
            "candidates": view(active),
            "sources": vehicle_sources(),
            "live_fetchers": enabled_live_fetchers(),
            "evaluation": evaluation,
            "error": error,
            "tax_rule_version": TAX_RULE_VERSION,
            "tax_retrieved": TAX_RULES_RETRIEVED_AT.date().isoformat(),
            "now": datetime.now(timezone.utc).isoformat(),
            "example": _EXAMPLE,
        },
    )


_EXAMPLE = """{
  "title": "Citroen Berlingo panel van",
  "as_of": "2026-09-22T12:00:00+00:00",
  "source_id": "cv_manual",
  "external_id": "example",
  "currency": "EUR"
}"""


@router.get("/cv", response_class=HTMLResponse)
def cv_dashboard(request: Request, view_name: str = "candidates") -> HTMLResponse:
    active = view_name if view_name in {"candidates", "manual", "price", "rejected", "insufficient", "all"} else "candidates"
    return _page(request, active=active)


@router.get("/cv/sources")
def cv_sources() -> JSONResponse:
    return JSONResponse(
        {
            "live_fetchers": list(enabled_live_fetchers()),
            "sources": [source.to_dict() for source in vehicle_sources()],
            "tax_rule_version": TAX_RULE_VERSION,
            "tax_rules_retrieved_at": TAX_RULES_RETRIEVED_AT.isoformat(),
            "purchasing_enabled": False,
        }
    )


@router.post("/cv/evaluate", response_class=HTMLResponse)
def cv_evaluate(request: Request, payload: str = Form(...)) -> HTMLResponse:
    try:
        case = case_from_payload(json.loads(payload))
        evaluation = evaluate_vehicle(case)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return _page(request, active="candidates", error=f"Could not evaluate that payload: {exc}")
    remember(evaluation)
    return _page(request, active="candidates", evaluation=evaluation.to_dict())


@router.post("/cv/api/evaluate")
def cv_evaluate_api(body: dict) -> JSONResponse:
    try:
        case = case_from_payload(body)
        evaluation = evaluate_vehicle(case)
    except (KeyError, TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    remember(evaluation)
    return JSONResponse(evaluation.to_dict())
