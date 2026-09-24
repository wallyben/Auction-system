"""T426 coverage replay 002. Frozen catalogue, current public-page observations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from app.domains.vehicles.browser_market.harvest import harvest_market_group
from app.domains.vehicles.browser_market.playwright_runtime import browser_session, fetch_with_retry, host_lock
from app.domains.vehicles.browser_market.base import PageFetch
from app.domains.vehicles.capture import _case
from app.domains.vehicles.evaluate import evaluate_vehicle
from app.domains.vehicles.ingest.mid_ulster import fee_schedule_eur
from app.domains.vehicles.ingest.t426_snapshot import body_for_hint, parse_t426_snapshot
from app.domains.vehicles.market import MarketBook
from app.domains.vehicles.market_search import groups_for_lots
from app.domains.vehicles.enums import BodyKind

INPUT = Path("artifacts/runtime/cv019/T426_CV019_INPUT_2026-09-23.txt")


def main() -> None:
    text = INPUT.read_text(encoding="utf-8")
    parsed, fx = parse_t426_snapshot(text)
    moment = datetime(2026, 9, 23, 21, 27, tzinfo=timezone.utc)
    schedule = fee_schedule_eur(parsed, fx_eur_per_gbp=fx, retrieved_at=moment)
    panel_lots = []
    for lot in parsed.lots:
        body = body_for_hint(lot.vendor_disclosure or "", lot.title)
        if body is not BodyKind.PANEL:
            continue
        panel_lots.append({"model_family": _family(lot.title), "year": lot.year, "body": "PANEL", "fuel": "DIESEL", "lot": lot})
    groups = groups_for_lots([{k: v for k, v in row.items() if k != "lot"} for row in panel_lots])
    book_rows = []
    with browser_session(timeout_ms=30000) as browser:
        def fetch(url: str) -> PageFetch:
            if "donedeal.ie" in url or "carsireland.ie" in url:
                return PageFetch(url, url, 403, "", challenge="BLOCKED_CHALLENGE")
            host = urlparse(url).netloc or "carzone.ie"
            with host_lock(host):
                return fetch_with_retry(browser, url)

        for group in groups:
            report = harvest_market_group(group, fetch, as_of=moment, delay_s=1.0)
            book_rows.extend(report.observations)
            print(json.dumps({"group": group.group_id, "unique_roi": report.unique_roi, "vat": report.vat_known, "stopped": report.stopped_reason}), flush=True)
    book = MarketBook(book_rows)
    rows = []
    for lot in parsed.lots:
        case = _case(lot, parsed, book, moment, schedule, fx, moment)
        if case is None:
            continue
        case.identity.body = body_for_hint(lot.vendor_disclosure or "", lot.title)
        evaluation = evaluate_vehicle(case)
        payload = evaluation.to_dict()
        rows.append(
            {
                "lot": lot.lot_number,
                "title": lot.title,
                "hint": lot.vendor_disclosure,
                "registration": lot.registration,
                "mileage_km": lot.mileage_km,
                "state": payload.get("state"),
                "confidence": (payload.get("valuation") or {}).get("confidence_label"),
                "conservative": (payload.get("valuation") or {}).get("conservative_eur"),
                "max_eur": payload.get("maximum_safe_bid_eur"),
                "comps": payload.get("irish_comparable_count"),
            }
        )
        print(json.dumps(rows[-1]), flush=True)
    out = Path("artifacts/runtime/cv019/T426_REPLAY_002.json")
    out.write_text(json.dumps({"fx": str(fx), "lots": rows}, indent=2), encoding="utf-8")


def _family(title: str) -> str:
    from app.domains.vehicles.identity import parse_listing_text

    return parse_listing_text(title).model_family or ""


if __name__ == "__main__":
    main()
