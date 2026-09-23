"""ARIE-CV owner surface. It does not bid, buy, or pay."""

from __future__ import annotations

import json
from decimal import Decimal
from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.domains.vehicles.board import remember, shadow_count, view
from app.domains.vehicles.capture import catalogue_to_cases, evaluate_cases
from app.domains.vehicles.certification_metrics import score_certification
from app.domains.vehicles.evaluate import evaluate_vehicle
from app.domains.vehicles.history_dvsa import dvsa_status
from app.domains.vehicles.ingest.dealer_feed import parse_dealer_feed
from app.domains.vehicles.owner_documents import apply_owner_document, parse_owner_document
from app.domains.vehicles.policy import TAX_RULE_VERSION, TAX_RULES_RETRIEVED_AT
from app.domains.vehicles.present import case_from_payload
from app.domains.vehicles.runtime_book import add_observations, current_book
from app.domains.vehicles.sources import enabled_live_fetchers, vehicle_sources

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


def _page(
    request: Request,
    *,
    active: str,
    evaluation: dict | None = None,
    error: str | None = None,
    notice: str | None = None,
) -> HTMLResponse:
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
            "notice": notice,
            "tax_rule_version": TAX_RULE_VERSION,
            "tax_retrieved": TAX_RULES_RETRIEVED_AT.date().isoformat(),
            "now": datetime.now(timezone.utc).isoformat(),
            "example": _EXAMPLE,
            "shadow_count": shadow_count(),
            "certification": score_certification(historical_cases=0, live_shadow_cases=shadow_count()),
            "dvsa": dvsa_status(),
            "book_size": len(current_book().observations),
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


@router.post("/cv/capture/mid-ulster", response_class=HTMLResponse)
def cv_capture_mid_ulster(
    request: Request,
    catalogue: str = Form(...),
    fx_eur_per_gbp: str = Form(""),
    fx_retrieved_at: str = Form(""),
) -> HTMLResponse:
    try:
        fx = Decimal(fx_eur_per_gbp) if fx_eur_per_gbp.strip() else None
        fx_at = datetime.fromisoformat(fx_retrieved_at) if fx_retrieved_at.strip() else None
        if fx_at is not None and fx_at.tzinfo is None:
            raise ValueError("FX timestamp must include a timezone.")
        parsed, cases = catalogue_to_cases(
            catalogue,
            current_book(),
            fx_eur_per_gbp=fx,
            fx_retrieved_at=fx_at,
        )
        evaluations = evaluate_cases(cases)
    except (ValueError, ArithmeticError) as exc:
        return _page(request, active="manual", error=f"Could not read that catalogue: {exc}")
    for evaluation in evaluations:
        remember(evaluation, freeze_shadow=True)
    summary = (
        f"Parsed sale {parsed.sale_code or 'unknown'} with parser {parsed.parser_version}. "
        f"{len(evaluations)} van lots evaluated. {parsed.skipped_not_vans} non-van lots skipped. "
        "Nothing was downloaded from the auction site. Buy candidates stay empty until the gates pass."
    )
    latest = evaluations[0].to_dict() if evaluations else None
    return _page(request, active="all", evaluation=latest, notice=summary)


@router.post("/cv/market/feed", response_class=HTMLResponse)
def cv_market_feed(request: Request, feed_text: str = Form(...)) -> HTMLResponse:
    try:
        rows = parse_dealer_feed(feed_text, observed_at=datetime.now(timezone.utc))
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        return _page(request, active="candidates", error=f"Could not read that feed: {exc}")
    inserted, duplicates = add_observations(rows)
    return _page(
        request,
        active="candidates",
        notice=f"Market book appended {inserted} observations. {duplicates} duplicates were rejected. Disappearance is not a sale.",
    )


@router.post("/cv/evidence", response_class=HTMLResponse)
def cv_evidence(
    request: Request,
    document: str = Form(...),
    payload: str = Form(""),
) -> HTMLResponse:
    try:
        parsed = parse_owner_document(json.loads(document))
        if not payload.strip():
            return _page(
                request,
                active="manual",
                notice=(
                    f"{parsed.kind} reference {parsed.reference} was accepted as a document record. "
                    "It does not pass a gate. Paste the vehicle case as well if you want it re-evaluated."
                ),
            )
        case = case_from_payload(json.loads(payload))
        apply_owner_document(case, parsed)
        case.owner_documents = case.owner_documents + (parsed,)
        evaluation = evaluate_vehicle(case)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return _page(request, active="manual", error=f"Could not attach that document: {exc}")
    remember(evaluation, freeze_shadow=True)
    return _page(request, active="manual", evaluation=evaluation.to_dict())
