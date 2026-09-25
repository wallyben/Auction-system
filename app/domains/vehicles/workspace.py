"""Persisted owner auctions. Valuation stays in the Python engine."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.vehicles.capture import _case, catalogue_to_cases, evaluate_vehicle
from app.domains.vehicles.ingest.mid_ulster import fee_schedule_eur
from app.domains.vehicles.ingest.t426_snapshot import parse_t426_snapshot
from app.domains.vehicles.enums import Fuel, ObservationStatus
from app.domains.vehicles.market import MarketBook, MarketObservation
from app.domains.vehicles.orm import CvAuctionRow, CvLotRow, CvOwnerEvidenceRow
from app.domains.vehicles.owner_documents import apply_owner_document, parse_owner_document
from app.domains.vehicles.owner_view import owner_status, plain_provenance

EVIDENCE_DIR = Path("artifacts/runtime/cv_evidence")
T426_PATH = Path("artifacts/runtime/cv019/T426_CV019_INPUT_2026-09-23.txt")
MESH_PATH = Path("artifacts/runtime/cv019/dealer_mesh_006e.json")


def import_catalogue(session: Session, text: str, *, fx: str = "") -> dict:
    book = book_from_cache()
    rate = Decimal(fx) if fx else None
    parsed, cases, rate = _cases_from_text(text, book, rate)
    auction_id = uuid.uuid4().hex[:16]
    now = datetime.now(timezone.utc)
    auction = CvAuctionRow(
        auction_id=auction_id,
        sale_code=parsed.sale_code or "sale",
        title=f"Mid Ulster {parsed.sale_code}" if parsed.sale_code else "Imported auction",
        source="catalogue",
        currency="GBP",
        fx=str(rate or ""),
        status="OPEN",
        closes_at=parsed.closes_at,
        created_at=now,
        payload={"catalogue": text},
    )
    session.add(auction)
    for case in cases:
        evaluation = evaluate_vehicle(case)
        report = evaluation.to_dict()
        lot_number = case.listing.external_id.rsplit("-", 1)[-1]
        session.add(_lot_row(auction_id, lot_number, case, report))
    session.commit()
    return auction_card(session, auction)


def seed_t426_if_empty(session: Session) -> str:
    existing = session.scalar(select(CvAuctionRow.auction_id).limit(1))
    if existing:
        return "present"
    if not T426_PATH.exists():
        return "missing-file"
    import_catalogue(session, T426_PATH.read_text(encoding="utf-8"))
    return "imported"


def list_auctions(session: Session) -> list[dict]:
    rows = session.scalars(select(CvAuctionRow).order_by(CvAuctionRow.created_at.desc())).all()
    return [auction_card(session, row) for row in rows]


def auction_detail(session: Session, auction_id: str) -> dict:
    auction = session.get(CvAuctionRow, auction_id)
    if auction is None:
        raise KeyError(auction_id)
    lots = session.scalars(select(CvLotRow).where(CvLotRow.auction_id == auction_id)).all()
    card = auction_card(session, auction)
    card["vehicles"] = [lot_card(row) for row in sorted(lots, key=lambda item: _lot_sort(item.lot_number))]
    return card


def lot_detail(session: Session, lot_id: str) -> dict:
    row = session.get(CvLotRow, lot_id)
    if row is None:
        raise KeyError(lot_id)
    card = lot_card(row)
    card["evaluation"] = row.payload.get("evaluation") or {}
    card["evidence"] = _evidence(session, lot_id)
    card["request_pack"] = request_pack(card)
    return card


def set_selection(session: Session, lot_id: str, *, selected: bool, note: str | None = None) -> dict:
    row = session.get(CvLotRow, lot_id)
    if row is None:
        raise KeyError(lot_id)
    row.selected = selected
    if note is not None:
        row.owner_note = note
    session.commit()
    return lot_card(row)


def set_bid(session: Session, lot_id: str, bid_gbp: str) -> dict:
    row = session.get(CvLotRow, lot_id)
    if row is None:
        raise KeyError(lot_id)
    row.current_bid_gbp = bid_gbp
    report = dict(row.payload.get("evaluation") or {})
    economics = dict(report.get("economics") or {})
    final = economics.get("final_max_safe_hammer_eur")
    economics["headroom_status"] = "UNKNOWN" if not final else economics.get("headroom_status")
    economics["current_bid_gbp"] = bid_gbp
    report["economics"] = economics
    report["current_bid_gbp"] = bid_gbp
    payload = dict(row.payload)
    payload["evaluation"] = report
    row.payload = payload
    session.commit()
    return lot_card(row)


def add_evidence(session: Session, lot_id: str, document: dict, *, filename: str = "", content: bytes = b"") -> dict:
    row = session.get(CvLotRow, lot_id)
    if row is None:
        raise KeyError(lot_id)
    evidence_id = uuid.uuid4().hex[:16]
    stored = ""
    if content and filename:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix.lower()
        if suffix not in {".pdf", ".jpg", ".jpeg", ".png"}:
            raise ValueError("Use a PDF, JPEG, or PNG.")
        target = EVIDENCE_DIR / f"{evidence_id}{suffix}"
        target.write_bytes(content)
        stored = str(target)
    session.add(
        CvOwnerEvidenceRow(
            evidence_id=evidence_id,
            vehicle_key=lot_id,
            kind=str(document.get("kind") or "other"),
            created_at=datetime.now(timezone.utc),
            payload={"document": document, "file": stored, "filename": filename},
        )
    )
    session.commit()
    _reevaluate(session, row)
    return lot_detail(session, lot_id)


def overview(session: Session) -> dict:
    auctions = list_auctions(session)
    lots = session.scalars(select(CvLotRow)).all()
    cards = [lot_card(row) for row in lots]
    return {
        "auctions": auctions,
        "counts": _counts(cards),
        "attention": [card for card in cards if card["selected"] or card["status"] == "TAX DILIGENCE"][:8],
    }


def shortlist(session: Session) -> list[dict]:
    rows = session.scalars(select(CvLotRow).where(CvLotRow.selected.is_(True))).all()
    return [lot_card(row) for row in rows]


def diligence_queue(session: Session) -> list[dict]:
    items = []
    for row in session.scalars(select(CvLotRow)).all():
        card = lot_card(row)
        if card["status"] not in {"TAX DILIGENCE", "MARKET READY"} and not card["selected"]:
            continue
        for blocker in card["blockers"]:
            items.append({"lot_id": card["lot_id"], "lot": card["lot_number"], "vehicle": card["vehicle"], "blocker": blocker, "status": card["status"], "pre_tax_ceiling": card["pre_tax_ceiling"]})
    return items


def auction_card(session: Session, auction: CvAuctionRow) -> dict:
    lots = session.scalars(select(CvLotRow).where(CvLotRow.auction_id == auction.auction_id)).all()
    cards = [lot_card(row) for row in lots]
    counts = _counts(cards)
    return {
        "auction_id": auction.auction_id,
        "sale_code": auction.sale_code,
        "title": auction.title,
        "source": auction.source,
        "currency": auction.currency,
        "fx": auction.fx,
        "status": auction.status,
        "closes_at": auction.closes_at.isoformat() if auction.closes_at else None,
        **counts,
    }


def lot_card(row: CvLotRow) -> dict:
    report = row.payload.get("evaluation") or {}
    economics = report.get("economics") or {}
    valuation = report.get("valuation") or {}
    return {
        "lot_id": row.lot_id,
        "auction_id": row.auction_id,
        "lot_number": row.lot_number,
        "title": row.title,
        "vehicle": report.get("vehicle") or row.title,
        "registration": row.registration,
        "year": row.payload.get("year"),
        "mileage_km": row.payload.get("mileage_km"),
        "status": row.owner_status,
        "technical_state": report.get("prebid_group"),
        "selected": row.selected,
        "note": row.owner_note,
        "current_bid_gbp": row.current_bid_gbp or None,
        "market_floor": valuation.get("conservative_eur"),
        "pre_tax_ceiling": economics.get("pre_tax_hammer_ceiling_eur"),
        "final_safe_hammer": economics.get("final_max_safe_hammer_eur"),
        "headroom_status": economics.get("headroom_status") or "UNKNOWN",
        "market_confidence": valuation.get("market_floor_confidence"),
        "dealer_diversity": valuation.get("dealer_diversity_status"),
        "provenance": report.get("provenance_status"),
        "provenance_plain": plain_provenance(str(report.get("provenance_status") or "")),
        "blockers": economics.get("blockers") or [],
        "buy_ready": bool(report.get("buy_ready")),
    }


def request_pack(card: dict) -> str:
    lines = [f"Lot {card['lot_number']} — {card['vehicle']}", "", "Please confirm or provide:"]
    for blocker in card["blockers"]:
        lines.append(f"- {blocker}")
    if not card["blockers"]:
        lines.append("- No open document request.")
    return "\n".join(lines)


def _cases_from_text(text: str, book: MarketBook, rate: Decimal | None):
    moment = datetime.now(timezone.utc)
    if "GBP_EUR:" in text or "| VAN |" in text or "| HGV |" in text:
        parsed, snapshot_fx = parse_t426_snapshot(text)
        rate = rate or snapshot_fx
    else:
        parsed, cases = catalogue_to_cases(text, book, fx_eur_per_gbp=rate, fx_retrieved_at=moment)
        return parsed, cases, rate
    schedule = fee_schedule_eur(parsed, fx_eur_per_gbp=rate, retrieved_at=moment)
    cases = []
    for lot in parsed.lots:
        case = _case(lot, parsed, book, moment, schedule, rate, moment)
        if case is not None:
            cases.append(case)
    return parsed, cases, rate


def book_from_cache() -> MarketBook:
    rows: list[MarketObservation] = []
    cache = Path("artifacts/runtime/browser_market")
    if cache.exists():
        for path in cache.glob("*.json"):
            if path.name == "groups.json":
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for card in payload.get("cards") or []:
                observation = _obs_from_card(card, str(card.get("source_id") or payload.get("source_id") or "cache"))
                if observation is not None:
                    rows.append(observation)
    if MESH_PATH.exists():
        try:
            mesh = json.loads(MESH_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            mesh = {}
        for item in mesh.get("observations") or []:
            observation = _obs_from_card(item, str(item.get("source") or "dealer"))
            if observation is not None:
                rows.append(observation)
    return MarketBook(rows)


def _obs_from_card(card: dict, source: str) -> MarketObservation | None:
    price = card.get("asking_price_eur") or card.get("price")
    if not price:
        return None
    family = str(card.get("model_family") or card.get("family") or "")
    if not family:
        return None
    moment = datetime.now(timezone.utc)
    url = str(card.get("url") or uuid.uuid4().hex)
    return MarketObservation(
        observation_id=f"cache-{url}"[:64],
        listing_id=url[:128],
        observed_at=moment,
        manufacturer=str(card.get("manufacturer") or ""),
        model_family=family,
        year=card.get("year"),
        fuel=Fuel.DIESEL,
        body=str(card.get("body") or "PANEL"),
        wheelbase=None,
        roof=None,
        transmission=None,
        derivative=None,
        mileage_km=card.get("mileage_km"),
        generation=None,
        asking_price_eur=Decimal(str(price)),
        realised_price_eur=None,
        seller_type="dealer",
        vat_presentation=str(card.get("vat_presentation") or "unknown"),
        location="Ireland",
        status=ObservationStatus.ACTIVE,
        source=source[:64],
        url=url,
        listing_title=str(card.get("title") or ""),
        dealer_name=str(card.get("dealer") or "") or None,
        vat_classification=str(card.get("vat_classification") or card.get("vat") or "UNKNOWN"),
    )


def _lot_row(auction_id: str, lot_number: str, case, report: dict) -> CvLotRow:
    return CvLotRow(
        lot_id=f"{auction_id}-{lot_number}",
        auction_id=auction_id,
        lot_number=lot_number,
        title=case.listing.title,
        registration=case.identity.registration or "",
        owner_status=owner_status(report),
        selected=False,
        owner_note="",
        current_bid_gbp=str(case.listing.current_bid or ""),
        payload={
            "year": case.identity.year,
            "mileage_km": case.identity.mileage_km,
            "evaluation": report,
        },
    )


def _reevaluate(session: Session, row: CvLotRow) -> None:
    auction = session.get(CvAuctionRow, row.auction_id)
    if auction is None:
        return
    text = str((auction.payload or {}).get("catalogue") or "")
    if not text:
        return
    _parsed, cases, _rate = _cases_from_text(text, book_from_cache(), Decimal(auction.fx) if auction.fx else None)
    case = next((item for item in cases if item.listing.external_id.rsplit("-", 1)[-1] == row.lot_number), None)
    if case is None:
        return
    if row.current_bid_gbp:
        case.listing.current_bid = Decimal(row.current_bid_gbp)
    for evidence in session.scalars(select(CvOwnerEvidenceRow).where(CvOwnerEvidenceRow.vehicle_key == row.lot_id)).all():
        document = (evidence.payload or {}).get("document") or {}
        try:
            parsed = parse_owner_document(document)
        except (KeyError, TypeError, ValueError):
            continue
        apply_owner_document(case, parsed)
        case.owner_documents = case.owner_documents + (parsed,)
    report = evaluate_vehicle(case).to_dict()
    payload = dict(row.payload)
    payload["evaluation"] = report
    row.payload = payload
    row.owner_status = owner_status(report)
    session.commit()


def _evidence(session: Session, lot_id: str) -> list[dict]:
    rows = session.scalars(select(CvOwnerEvidenceRow).where(CvOwnerEvidenceRow.vehicle_key == lot_id)).all()
    return [{"evidence_id": row.evidence_id, "kind": row.kind, "created_at": row.created_at.isoformat(), "filename": (row.payload or {}).get("filename") or ""} for row in rows]


def _counts(cards: list[dict]) -> dict:
    def n(status: str) -> int:
        return sum(1 for card in cards if card["status"] == status)

    return {
        "lots": len(cards),
        "market_ready": n("MARKET READY"),
        "tax_diligence": n("TAX DILIGENCE"),
        "market_insufficient": n("MARKET INSUFFICIENT"),
        "hard_reject": n("HARD REJECT"),
        "selected": sum(1 for card in cards if card["selected"]),
        "priced": sum(1 for card in cards if card["market_floor"]),
    }


def _lot_sort(value: str) -> tuple:
    return (0, int(value)) if value.isdigit() else (1, value)
