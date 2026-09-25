"""JSON API for the owner application. The Python engine remains authoritative."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.ops import get_db
from app.core.config import settings
from app.domains.vehicles.market_provider import source_health
from app.models.orm import PipelineJob
from app.domains.vehicles.workspace import (
    add_evidence,
    auction_detail,
    diligence_queue,
    import_catalogue,
    list_auctions,
    lot_detail,
    overview,
    seed_t426_if_empty,
    set_bid,
    set_selection,
    shortlist,
)
from app.jobs.queue import enqueue_http

router = APIRouter(prefix="/api/cv/v1")


def _guard(x_arie_token: str | None = Header(default=None)) -> None:
    expected = (settings.arie_dashboard_token or "").strip()
    if expected and x_arie_token != expected:
        raise HTTPException(status_code=401, detail="Owner token required")


@router.get("/overview")
def get_overview(session: Session = Depends(get_db), _: None = Depends(_guard)) -> dict:
    seed_t426_if_empty(session)
    return overview(session)


@router.get("/auctions")
def get_auctions(session: Session = Depends(get_db), _: None = Depends(_guard)) -> dict:
    seed_t426_if_empty(session)
    return {"auctions": list_auctions(session)}


@router.post("/auctions/import")
def post_import(body: dict, session: Session = Depends(get_db), _: None = Depends(_guard)) -> dict:
    text = str(body.get("catalogue") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Paste or upload a catalogue")
    try:
        return import_catalogue(session, text, fx=str(body.get("fx") or ""))
    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/auctions/{auction_id}")
def get_auction(auction_id: str, session: Session = Depends(get_db), _: None = Depends(_guard)) -> dict:
    try:
        return auction_detail(session, auction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Auction not found") from exc


@router.post("/auctions/{auction_id}/refresh")
def post_refresh(auction_id: str, _: None = Depends(_guard)) -> dict:
    queued = enqueue_http("cv-market-refresh", "owner", {"auction_id": auction_id})
    return {"queued": bool(queued.get("ok")), "job": queued}


@router.get("/lots/{lot_id}")
def get_lot(lot_id: str, session: Session = Depends(get_db), _: None = Depends(_guard)) -> dict:
    try:
        return lot_detail(session, lot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Vehicle not found") from exc


@router.post("/lots/{lot_id}/selection")
def post_selection(lot_id: str, body: dict, session: Session = Depends(get_db), _: None = Depends(_guard)) -> dict:
    try:
        return set_selection(session, lot_id, selected=bool(body.get("selected")), note=body.get("note"))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Vehicle not found") from exc


@router.post("/lots/{lot_id}/bid")
def post_bid(lot_id: str, body: dict, session: Session = Depends(get_db), _: None = Depends(_guard)) -> dict:
    try:
        return set_bid(session, lot_id, str(body.get("bid_gbp") or ""))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Vehicle not found") from exc


@router.post("/lots/{lot_id}/evidence")
def post_evidence(
    lot_id: str,
    kind: str = Form(...),
    reference: str = Form(""),
    jurisdiction: str = Form(""),
    file: UploadFile | None = File(default=None),
    session: Session = Depends(get_db),
    _: None = Depends(_guard),
) -> dict:
    content = file.file.read() if file is not None else b""
    document = {"kind": kind, "reference": reference or kind, "jurisdiction": jurisdiction or None, "resident_in": jurisdiction or None}
    try:
        return add_evidence(session, lot_id, document, filename=file.filename if file else "", content=content)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Vehicle not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/shortlist")
def get_shortlist(session: Session = Depends(get_db), _: None = Depends(_guard)) -> dict:
    return {"lots": shortlist(session)}


@router.get("/diligence")
def get_diligence(session: Session = Depends(get_db), _: None = Depends(_guard)) -> dict:
    return {"tasks": diligence_queue(session)}


@router.get("/sources")
def get_sources(_: None = Depends(_guard)) -> dict:
    return {"sources": source_health()}


@router.get("/market")
def get_market(session: Session = Depends(get_db), _: None = Depends(_guard)) -> dict:
    from app.domains.vehicles.orm import CvAuctionRow, CvLotRow
    from app.domains.vehicles.workspace import lot_card

    fx_by_auction = {row.auction_id: row.fx for row in session.scalars(select(CvAuctionRow)).all()}
    cards = [lot_card(row, fx=fx_by_auction.get(row.auction_id, "")) for row in session.scalars(select(CvLotRow)).all()]
    return {"priced": sum(1 for card in cards if card["market_floor"]), "lots": len(cards), "vehicles": cards[:40]}


@router.get("/jobs")
def get_jobs(session: Session = Depends(get_db), _: None = Depends(_guard)) -> dict:
    rows = session.scalars(select(PipelineJob).order_by(PipelineJob.created_at.desc()).limit(20)).all()
    return {
        "jobs": [
            {
                "id": str(row.id),
                "name": row.name,
                "status": row.status,
                "error": row.error,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            }
            for row in rows
        ]
    }
