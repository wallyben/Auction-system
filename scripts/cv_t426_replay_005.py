"""T426 coverage replay 005. Landed-cost semantics. Does not overwrite replay 004."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.domains.vehicles.browser_market.base import PageFetch
from app.domains.vehicles.browser_market.dealer_generic import parse_dealer
from app.domains.vehicles.browser_market.harvest import harvest_market_group
from app.domains.vehicles.browser_market.playwright_runtime import browser_session, fetch_with_retry, host_lock
from app.domains.vehicles.capture import _case
from app.domains.vehicles.evaluate import evaluate_vehicle
from app.domains.vehicles.enums import BodyKind
from app.domains.vehicles.ingest.mid_ulster import fee_schedule_eur
from app.domains.vehicles.ingest.t426_snapshot import body_for_hint, parse_t426_snapshot
from app.domains.vehicles.market import MarketBook, MarketObservation
from app.domains.vehicles.market_provider import BRAVE_ENDPOINT, brave_api_key
from app.domains.vehicles.market_search import groups_for_lots
from app.domains.vehicles.scenarios import prebid_economic_group

INPUT = Path("artifacts/runtime/cv019/T426_CV019_INPUT_2026-09-23.txt")
OUTPUT = Path("artifacts/runtime/cv019/T426_REPLAY_005.json")
MESH = Path("artifacts/runtime/cv019/dealer_mesh_006e.json")
BLOCKED = ("donedeal.ie", "carsireland.ie", "carzone.ie", "autotrader", "ebay.")


def main() -> None:
    text = INPUT.read_text(encoding="utf-8")
    parsed, fx = parse_t426_snapshot(text)
    moment = datetime.now(timezone.utc)
    schedule = fee_schedule_eur(parsed, fx_eur_per_gbp=fx, retrieved_at=moment)
    panel_lots = []
    for lot in parsed.lots:
        body = body_for_hint(lot.vendor_disclosure or "", lot.title)
        if body is not BodyKind.PANEL:
            continue
        panel_lots.append({"model_family": _family(lot.title), "year": lot.year, "body": "PANEL", "fuel": "DIESEL", "lot": lot})
    groups = groups_for_lots([{key: value for key, value in row.items() if key != "lot"} for row in panel_lots])
    dealer_log = {"sources": [], "cards": 0, "combo": 0, "challenges": [], "thin": []}
    book_rows: list[MarketObservation] = []
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
            if report.unique_roi < 8:
                dealer_log["thin"].append(group.model_family)
    book_rows.extend(_mesh_observations(moment))
    from app.domains.vehicles.market_dedupe import assign_duplicate_groups, primary_observations

    book_rows = primary_observations(assign_duplicate_groups(book_rows))
    book = MarketBook(book_rows)
    rows = []
    for lot in parsed.lots:
        case = _case(lot, parsed, book, moment, schedule, fx, moment)
        if case is None:
            continue
        case.identity.body = body_for_hint(lot.vendor_disclosure or "", lot.title)
        if case.identity.body is not BodyKind.PANEL:
            continue
        evaluation = evaluate_vehicle(case)
        valued = evaluation.valuation
        report = evaluation.to_dict()
        group = str(report["prebid_group"])
        economics = report.get("economics") or {}
        payload = {
            "lot": lot.lot_number,
            "vehicle": evaluation.summary_vehicle,
            "year": case.identity.year,
            "mileage_km": case.identity.mileage_km,
            "unique_roi_comps": valued.comparable_count,
            "close_comps": valued.close_count,
            "effective_sample": str(valued.effective_sample_size),
            "vat_explicit_count": valued.known_vat_share,
            "vat_basis_confidence": valued.vat_basis_confidence,
            "market_cash_low": _s(valued.market_cash_low_eur),
            "market_cash_central_low": _s(valued.market_cash_central_low_eur),
            "market_cash_central_high": _s(valued.market_cash_central_high_eur),
            "market_cash_high": _s(valued.market_cash_high_eur),
            "expected_low": _s(valued.expected_achievable_low_eur),
            "expected_high": _s(valued.expected_achievable_high_eur),
            "conservative_resale_floor": _s(valued.conservative_eur),
            "vat_stress_proceeds": _s(valued.vat_stress_proceeds_eur),
            "market_floor_confidence": valued.market_floor_confidence,
            "max_hammer_market_floor_eur": _s(valued.max_hammer_market_floor_eur),
            "max_hammer_vat_stress_eur": _s(valued.max_hammer_vat_stress_eur),
            "max_hammer_confirmed_tax_eur": _s(valued.max_hammer_confirmed_tax_eur),
            "max_hammer_vat_stress_gbp": _gbp(valued.max_hammer_vat_stress_eur, fx),
            "dealer_count": valued.dealer_count,
            "largest_dealer_share": valued.largest_dealer_share,
            "prebid_floor": "YES" if valued.prebid_floor_available else "NO",
            "prebid_group": group,
            "dealer_diversity": valued.dealer_diversity_status,
            "pre_tax_ceiling": economics.get("pre_tax_hammer_ceiling_eur"),
            "ni_clear_hammer": economics.get("ni_clear_max_hammer_eur"),
            "gb_preferential_hammer": economics.get("gb_preferential_max_hammer_eur"),
            "gb_confirmed_duty_hammer": economics.get("gb_confirmed_duty_max_hammer_eur"),
            "final_safe_hammer": economics.get("final_max_safe_hammer_eur"),
            "headroom_status": economics.get("headroom_status"),
            "blockers": economics.get("blockers"),
            "state": evaluation.state.value,
            "buy_ready": evaluation.to_dict()["buy_ready"],
            "provenance": evaluation.provenance.state.value,
            "tax_blocked": evaluation.tax.blocked,
            "failures": evaluation.gates.failures,
        }
        rows.append(payload)
        print(json.dumps({"lot": payload["lot"], "group": group, "floor": payload["prebid_floor"], "stress": payload["max_hammer_vat_stress_eur"]}), flush=True)
    floors = sum(1 for row in rows if row["prebid_floor"] == "YES")
    summary = {
        "fx": str(fx),
        "ordinary_panel_vans": len(rows),
        "prebid_floor_available": floors,
        "coverage_pct": round(100 * floors / len(rows), 1) if rows else 0,
        "market_floor": _count(rows, "market_floor_confidence"),
        "conservative_resale_floors": sum(1 for row in rows if row["conservative_resale_floor"]),
        "vat_stress_max_hammers": sum(1 for row in rows if row["max_hammer_vat_stress_eur"]),
        "confirmed_tax_max_hammers": sum(1 for row in rows if row["max_hammer_confirmed_tax_eur"]),
        "groups": _count(rows, "prebid_group"),
        "dealer": dealer_log,
        "lots": rows,
    }
    OUTPUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in summary if key != "lots"}))


def _mesh_observations(moment: datetime) -> list[MarketObservation]:
    from app.domains.vehicles.enums import Fuel, ObservationStatus

    if not MESH.exists():
        return []
    payload = json.loads(MESH.read_text(encoding="utf-8"))
    rows: list[MarketObservation] = []
    for item in payload.get("observations") or []:
        price = item.get("price")
        if not price:
            continue
        url = str(item.get("url") or "")
        rows.append(
            MarketObservation(
                observation_id=f"mesh-{url}",
                listing_id=url,
                observed_at=moment,
                manufacturer="",
                model_family=str(item.get("family") or ""),
                year=item.get("year"),
                fuel=Fuel.DIESEL,
                body="PANEL",
                wheelbase=None,
                roof=None,
                transmission=None,
                derivative=None,
                mileage_km=item.get("mileage_km"),
                generation=None,
                asking_price_eur=Decimal(str(price)),
                realised_price_eur=None,
                seller_type="dealer",
                vat_presentation="ex_vat" if item.get("vat") == "VAT_EXCLUSIVE" else "unknown",
                location="Ireland",
                status=ObservationStatus.ACTIVE,
                source=str(item.get("source") or "dealer"),
                url=url,
                listing_title=str(item.get("title") or ""),
                dealer_name=str(item.get("dealer") or ""),
                registration=_reg(url),
                vat_classification=str(item.get("vat") or "UNKNOWN"),
                vat_fragment=str(item.get("vat_fragment") or ""),
            )
        )
    return rows


def _reg(url: str) -> str | None:
    import re

    match = re.search(r"/(\d{2,3}[a-z]{1,2}\d+)-", url, re.I)
    return match.group(1).upper() if match else None


def _dealer_fill(browser, family: str, fetch, moment: datetime, log: dict) -> list[MarketObservation]:
    del fetch
    label = family.replace("_", " ")
    urls = _discover(f"{label} van for sale Ireland dealer")
    found: list[MarketObservation] = []
    for url in urls[:3]:
        host = urlparse(url).netloc
        log["sources"].append(url)
        with host_lock(host):
            page = fetch_with_retry(browser, url)
        if page.challenge:
            log["challenges"].append({"url": url, "challenge": page.challenge})
            continue
        cards = parse_dealer(page.html or "", page.final_url or url)
        log["cards"] += len(cards)
        for card in cards:
            title = (card.title or "").lower()
            if family.replace("_", " ") not in title and family not in title and (card.model_family or "") != family:
                continue
            if card.asking_price_eur is None:
                continue
            if "combo" in family and "combo" in title:
                log["combo"] += 1
            found.append(_obs_from_card(card, moment))
    return found


def _discover(query: str) -> list[str]:
    key = brave_api_key()
    if not key:
        print(json.dumps({"dealer_search": "NOT_CONFIGURED"}), flush=True)
        return []
    try:
        response = httpx.get(
            BRAVE_ENDPOINT,
            params={"q": query, "country": "ALL", "search_lang": "en", "count": "8"},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
            timeout=20,
        )
        payload = response.json() if response.status_code == 200 else {}
        print(json.dumps({"dealer_search": response.status_code, "hits": len((payload.get("web") or {}).get("results") or [])}), flush=True)
    except Exception as exc:
        print(json.dumps({"dealer_search": "ERROR", "kind": type(exc).__name__}), flush=True)
        return []
    urls = []
    for hit in (payload.get("web") or {}).get("results") or []:
        url = str(hit.get("url") or "")
        if any(token in url.lower() for token in BLOCKED):
            continue
        if ".ie" not in url.lower():
            continue
        urls.append(url)
    return urls


def _obs_from_card(card, moment: datetime) -> MarketObservation:
    from app.domains.vehicles.enums import Fuel, ObservationStatus

    return MarketObservation(
        observation_id=f"dealer-{card.url}",
        listing_id=card.url,
        observed_at=moment,
        manufacturer=card.manufacturer or "",
        model_family=card.model_family or "",
        year=card.year,
        fuel=Fuel.DIESEL,
        body=card.body or "PANEL",
        wheelbase=None,
        roof=None,
        transmission=None,
        derivative=None,
        mileage_km=card.mileage_km,
        generation=None,
        asking_price_eur=card.asking_price_eur,
        realised_price_eur=None,
        seller_type="dealer",
        vat_presentation=card.vat_presentation or "unknown",
        location=card.location or "Ireland",
        status=ObservationStatus.ACTIVE,
        source=card.source_id or "browser-dealer-1",
        url=card.url,
        listing_title=card.title,
        vat_classification=card.vat_classification or "UNKNOWN",
    )


def _family(title: str) -> str:
    from app.domains.vehicles.identity import parse_listing_text

    return parse_listing_text(title).model_family or ""


def _s(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _gbp(eur: Decimal | None, fx: Decimal) -> str | None:
    if eur is None or fx <= 0:
        return None
    return str((eur / fx).quantize(Decimal("0.01")))


def _count(rows: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        label = str(row.get(key) or "")
        counts[label] = counts.get(label, 0) + 1
    return counts


if __name__ == "__main__":
    main()
