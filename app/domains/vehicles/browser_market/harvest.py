"""Open public search pages for one market group and stop when Native v2 can decide."""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from app.domains.vehicles.browser_market import ADAPTER_VERSION, EVIDENCE_CLASS, RIGHTS_STATUS, TECHNICAL_STATUS
from app.domains.vehicles.browser_market.adapters import ADAPTERS, CARSIRELAND, CARZONE, DEALER, DONEDEAL
from app.domains.vehicles.browser_market.base import ListingCard, PageFetch, SourcePageResult
from app.domains.vehicles.browser_market.cache import load_cached, store_cached
from app.domains.vehicles.browser_market.generic_cards import extract_cards
from app.domains.vehicles.browser_market.html_tree import parse_html
from app.domains.vehicles.browser_market.pagination import next_page_url
from app.domains.vehicles.browser_market.urls import classify_market_url, is_listing, result_urls
from app.domains.vehicles.enums import Fuel, ObservationStatus
from app.domains.vehicles.market import MarketBook, MarketObservation
from app.domains.vehicles.market_dedupe import assign_duplicate_groups, primary_observations
from app.domains.vehicles.market_extract import price_plausible_for_family
from app.domains.vehicles.market_harvest import decision_usable
from app.domains.vehicles.market_search import MarketGroup, family_label

Fetcher = Callable[[str], PageFetch]

_ORDER = (DONEDEAL, CARSIRELAND, CARZONE, DEALER)


def _limit(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


@dataclass(slots=True)
class BrowserHarvestReport:
    market_group_id: str
    pages_opened: int = 0
    result_pages: int = 0
    raw_cards: int = 0
    enriched: int = 0
    accepted: int = 0
    rejected: int = 0
    duplicates: int = 0
    unique_roi: int = 0
    mileage_known: int = 0
    vat_known: int = 0
    stopped_reason: str = ""
    observations: list[MarketObservation] = field(default_factory=list)
    sources: dict[str, SourcePageResult] = field(default_factory=dict)
    brave_requests: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "market_group_id": self.market_group_id,
            "pages_opened": self.pages_opened,
            "result_pages": self.result_pages,
            "raw_cards": self.raw_cards,
            "enriched": self.enriched,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "duplicates": self.duplicates,
            "unique_roi": self.unique_roi,
            "mileage_known": self.mileage_known,
            "vat_known": self.vat_known,
            "stopped_reason": self.stopped_reason,
            "brave_requests": self.brave_requests,
            "sources": {
                key: {
                    "pages": row.pages_opened,
                    "cards": row.cards,
                    "accepted": row.accepted,
                    "vat_known": row.vat_known,
                    "challenge": row.challenge,
                    "status": row.status,
                }
                for key, row in self.sources.items()
            },
        }


def select_enrichments(cards: list[ListingCard], *, limit: int) -> list[ListingCard]:
    """Open a listing only when a missing fact blocks the sample. Cap the visits."""

    priced = [card for card in cards if card.asking_price_eur and not card.rejection]
    if not priced:
        return []
    vat_known = sum(1 for card in priced if card.vat_classification not in {"", "VAT_UNKNOWN", "UNKNOWN"})
    need_vat = vat_known < max(2, len(priced) // 4)
    ranked: list[tuple[int, ListingCard]] = []
    for card in priced:
        score = 0
        if need_vat and card.vat_classification in {"", "VAT_UNKNOWN", "UNKNOWN"}:
            score += 4
        if card.mileage_km is None:
            score += 2
        if card.year is None:
            score += 2
        if card.body in {"", "UNKNOWN"}:
            score += 1
        if card.geography == "UNKNOWN":
            score += 1
        if score:
            ranked.append((score, card))
    ranked.sort(key=lambda item: item[0], reverse=True)
    chosen: list[ListingCard] = []
    seen: set[str] = set()
    for _score, card in ranked:
        if card.url in seen:
            continue
        seen.add(card.url)
        chosen.append(card)
        if len(chosen) >= limit:
            break
    return chosen


def harvest_market_group(
    group: MarketGroup,
    fetcher: Fetcher,
    *,
    existing: list[MarketObservation] | None = None,
    discovered: dict[str, list[str]] | None = None,
    as_of: datetime | None = None,
    delay_s: float | None = None,
) -> BrowserHarvestReport:
    moment = as_of or datetime.now(timezone.utc)
    report = BrowserHarvestReport(group.group_id)
    rows = list(existing or [])
    pages_cap = _limit("CV_BROWSER_MAX_PAGES_PER_SOURCE_GROUP", 5)
    enrich_cap = _limit("CV_BROWSER_MAX_LISTING_ENRICHMENTS_PER_GROUP", 12)
    pause = 1.5 if delay_s is None else delay_s
    targets = _targets(group, discovered or {})
    from app.domains.vehicles.market_harvest import _subject

    subject = _subject(group, moment)
    if decision_usable(subject, MarketBook(primary_observations(rows)), moment):
        report.stopped_reason = "SUFFICIENT"
        report.observations = primary_observations(assign_duplicate_groups(rows))
        _finish(report, rows)
        return report
    for source_id in _ORDER:
        source = SourcePageResult(source_id=source_id)
        report.sources[source_id] = source
        if decision_usable(subject, MarketBook(primary_observations(rows)), moment):
            report.stopped_reason = "SUFFICIENT"
            break
        parser = ADAPTERS[source_id]
        seen_urls: set[str] = set()
        for start in targets.get(source_id, []):
            if source.pages_opened >= pages_cap:
                break
            page_url = start
            hops = 0
            while page_url and hops < pages_cap and source.pages_opened < pages_cap:
                cached = load_cached(source_id, group.group_id, page_url, now=moment)
                if cached is not None:
                    cards = [_card_from_cache(item, source_id) for item in cached]
                    html = ""
                else:
                    if pause and hops:
                        time.sleep(pause)
                    fetched = fetcher(page_url)
                    report.pages_opened += 1
                    source.pages_opened += 1
                    hops += 1
                    if fetched.challenge:
                        source.challenge = fetched.challenge
                        source.status = fetched.challenge
                        break
                    html = fetched.html
                    cards = parser(html, fetched.final_url or page_url)
                    store_cached(source_id, group.group_id, page_url, cards, now=moment)
                report.result_pages += 1
                fresh = [card for card in cards if card.url not in seen_urls]
                for card in fresh:
                    seen_urls.add(card.url)
                report.raw_cards += len(fresh)
                source.cards += len(fresh)
                accepted, rejected = _accept(group, fresh, moment)
                rows.extend(accepted)
                source.accepted += len(accepted)
                source.vat_known += sum(1 for row in accepted if row.vat_presentation not in {"", "unknown"})
                report.rejected += rejected
                if not html:
                    break
                nxt = next_page_url(parse_html(html), page_url)
                if not nxt or nxt == page_url:
                    break
                page_url = nxt
            if source.challenge:
                break
        if source.challenge:
            continue
        source.status = "LIVE" if source.accepted else ("THIN" if source.pages_opened else "NOT_TESTED")
        if not decision_usable(subject, MarketBook(primary_observations(rows)), moment):
            chosen = select_enrichments(
                [card for card in _cards_of(rows, source_id)],
                limit=max(0, enrich_cap - report.enriched),
            )
            for card in chosen:
                if report.enriched >= enrich_cap:
                    break
                fetched = fetcher(card.url)
                report.pages_opened += 1
                report.enriched += 1
                source.enriched += 1
                if fetched.challenge:
                    source.challenge = fetched.challenge
                    if source.accepted == 0:
                        source.status = fetched.challenge
                    break
                enriched = parser(fetched.html, fetched.final_url or card.url)
                match = next((item for item in enriched if item.url.split("?")[0] == card.url.split("?")[0]), None)
                if match is None and enriched:
                    match = enriched[0]
                    match.url = card.url
                if match is None:
                    continue
                accepted, rejected = _accept(group, [match], moment, replace_url=card.url)
                report.rejected += rejected
                rows.extend(accepted)
        if source.challenge and source.status == "NOT_TESTED":
            source.status = source.challenge
    grouped = assign_duplicate_groups(rows)
    primary = primary_observations(grouped)
    report.observations = [row for row in primary if str(row.source).startswith("browser-") or row in (existing or [])]
    if existing:
        report.observations = primary
    else:
        report.observations = primary
    report.duplicates = len(grouped) - len(primary)
    if not report.stopped_reason:
        report.stopped_reason = "SUFFICIENT" if decision_usable(subject, MarketBook(primary), moment) else "THIN"
    _finish(report, primary)
    return report


def _finish(report: BrowserHarvestReport, rows: list[MarketObservation]) -> None:
    roi = [row for row in rows if row.geography == "ROI" and row.asking_price_eur]
    report.unique_roi = len({row.cross_source_duplicate_group_id or row.observation_id for row in roi}) if any(row.cross_source_duplicate_group_id for row in roi) else len(roi)
    report.vat_known = sum(1 for row in roi if row.vat_presentation not in {"", "unknown"})
    report.mileage_known = sum(1 for row in roi if row.mileage_km)
    report.accepted = len(rows)


def _targets(group: MarketGroup, discovered: dict[str, list[str]]) -> dict[str, list[str]]:
    built = {source: [url] for source, url in result_urls(group)}
    for source, urls in discovered.items():
        built.setdefault(source, [])
        for url in urls:
            if url not in built[source] and not is_listing(classify_market_url(url)):
                built[source].append(url)
    built.setdefault(DEALER, [])
    return built


def _accept(
    group: MarketGroup,
    cards: list[ListingCard],
    moment: datetime,
    *,
    replace_url: str = "",
) -> tuple[list[MarketObservation], int]:
    accepted: list[MarketObservation] = []
    rejected = 0
    for card in cards:
        if replace_url:
            card.url = replace_url
        if card.rejection or card.price_status != "PRICE_PLAUSIBLE" or card.asking_price_eur is None:
            rejected += 1
            continue
        if card.geography not in {"ROI", "UNKNOWN"}:
            rejected += 1
            continue
        if card.geography == "UNKNOWN" and card.url.endswith(".ie") is False and ".ie/" not in card.url:
            rejected += 1
            continue
        if price_plausible_for_family(card.asking_price_eur, group.model_family) != "PRICE_PLAUSIBLE":
            rejected += 1
            continue
        if card.body not in {"", "UNKNOWN", "PANEL"} and group.body == "PANEL" and card.body != "PANEL":
            rejected += 1
            continue
        centre = group.year_from + 1
        if card.year and abs(card.year - centre) > 6:
            rejected += 1
            continue
        if card.model_family and card.model_family != group.model_family:
            rejected += 1
            continue
        if card.geography == "UNKNOWN":
            card.geography = "ROI"
            card.geography_evidence = card.geography_evidence or "url:.ie"
        accepted.append(_observation(group, card, moment))
    return accepted, rejected


def _observation(group: MarketGroup, card: ListingCard, moment: datetime) -> MarketObservation:
    listing_id = hashlib.sha256(card.url.encode()).hexdigest()[:24]
    label = family_label(group.model_family)
    make = label.split()[0]
    fuel = Fuel.DIESEL if card.fuel == "DIESEL" else (_fuel(card.fuel) if card.fuel else Fuel.UNKNOWN)
    return MarketObservation(
        observation_id=f"{card.source_id}-{listing_id}-{int(moment.timestamp())}",
        listing_id=listing_id,
        observed_at=moment,
        manufacturer=card.manufacturer or make,
        model_family=card.model_family or group.model_family,
        year=card.year,
        fuel=fuel,
        body=group.body if card.body in {"", "UNKNOWN", "PANEL"} else card.body,
        wheelbase=card.wheelbase or None,
        roof=card.roof or None,
        transmission=card.transmission or None,
        derivative=card.derivative or None,
        mileage_km=card.mileage_km,
        generation=None,
        asking_price_eur=card.asking_price_eur,
        realised_price_eur=None,
        seller_type="dealer" if card.dealer else "unknown",
        vat_presentation=card.vat_presentation,
        location=card.location,
        status=ObservationStatus.ACTIVE,
        source=card.source_id,
        url=card.url,
        listing_title=card.title[:180],
        dealer_name=card.dealer or None,
        vat_classification=card.vat_classification,
        vat_fragment=card.vat_fragment[:180],
        parser_version=ADAPTER_VERSION,
        source_type=EVIDENCE_CLASS,
        capture_method="public-browser",
        evidence_quality=EVIDENCE_CLASS,
        geography="ROI" if card.geography == "ROI" else card.geography,
        price_status=card.price_status,
        mileage_evidence=card.mileage_evidence[:180],
        price_evidence=card.price_evidence[:180],
        listing_class=card.listing_class,
        raw_reference=f"{TECHNICAL_STATUS}|{RIGHTS_STATUS}",
        registration=card.registration or None,
        engine=card.engine or None,
    )


def _fuel(name: str) -> Fuel:
    try:
        return Fuel(name)
    except ValueError:
        return Fuel.UNKNOWN


def _presentation(classification: str) -> str:
    return {
        "VAT_EXCLUSIVE": "ex_vat",
        "VAT_INCLUSIVE": "vat_inclusive",
        "VAT_QUALIFYING": "qualifying",
        "NO_VAT": "no_vat",
        "MARGIN_SCHEME": "margin_scheme",
    }.get(classification, "unknown")


def _card_from_cache(item: dict, source_id: str) -> ListingCard:
    price = item.get("asking_price_eur")
    return ListingCard(
        url=str(item.get("url") or ""),
        listing_class=str(item.get("listing_class") or ""),
        title=str(item.get("title") or ""),
        source_id=source_id,
        manufacturer=str(item.get("manufacturer") or ""),
        model_family=str(item.get("model_family") or ""),
        year=item.get("year"),
        mileage_km=item.get("mileage_km"),
        asking_price_eur=Decimal(price) if price else None,
        vat_classification=str(item.get("vat_classification") or "VAT_UNKNOWN"),
        vat_fragment=str(item.get("vat_fragment") or ""),
        vat_presentation=str(item.get("vat_presentation") or _presentation(str(item.get("vat_classification") or ""))),
        body=str(item.get("body") or "UNKNOWN"),
        geography=str(item.get("geography") or "UNKNOWN"),
        dealer=str(item.get("dealer") or ""),
        price_status=str(item.get("price_status") or ""),
        rejection=str(item.get("rejection") or ""),
        location=str(item.get("location") or ""),
        fuel=str(item.get("fuel") or ""),
        transmission=str(item.get("transmission") or ""),
    )


def _cards_of(rows: list[MarketObservation], source_id: str) -> list[ListingCard]:
    cards: list[ListingCard] = []
    for row in rows:
        if row.source != source_id:
            continue
        cards.append(
            ListingCard(
                url=row.url or "",
                listing_class=row.listing_class,
                title=row.listing_title or "",
                source_id=source_id,
                model_family=row.model_family,
                year=row.year,
                mileage_km=row.mileage_km,
                asking_price_eur=row.asking_price_eur,
                vat_classification=row.vat_classification,
                vat_presentation=row.vat_presentation,
                body=row.body,
                geography=row.geography,
                price_status=row.price_status or "PRICE_PLAUSIBLE",
            )
        )
    return cards


def discover_result_urls(hits: list[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {DONEDEAL: [], CARSIRELAND: [], CARZONE: [], DEALER: []}
    for url in hits:
        kind = classify_market_url(url)
        if kind == "DONEDEAL_RESULTS":
            found[DONEDEAL].append(url)
        elif kind == "CARSIRELAND_RESULTS":
            found[CARSIRELAND].append(url)
        elif kind == "CARZONE_RESULTS":
            found[CARZONE].append(url)
        elif kind == "UNKNOWN" and ".ie" in url and not is_listing(kind):
            found[DEALER].append(url)
    return found
