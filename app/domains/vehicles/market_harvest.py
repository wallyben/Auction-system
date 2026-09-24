"""Harvest Irish market evidence for a market group and stop when v2 can decide."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from app.domains.vehicles.commoncrawl import ArchiveCapture, CommonCrawlMarketEnricher
from app.domains.vehicles.enums import Fuel, ObservationStatus
from app.domains.vehicles.identity import VehicleIdentity, parse_listing_text
from app.domains.vehicles.market import MarketBook, MarketObservation
from app.domains.vehicles.market_dedupe import assign_duplicate_groups, primary_observations
from app.domains.vehicles.market_extract import extract_listing, price_plausible_for_family
from app.domains.vehicles.market_provider import (
    BraveMarketSearchProvider,
    MarketSearchProvider,
    SearchBudget,
    SearchHit,
    SearchNotConfigured,
    SearchRejected,
    brave_configured,
    search_enabled,
)
from app.domains.vehicles.market_search import MarketGroup, SearchQuery, queries_for, vat_queries
from app.domains.vehicles.valuation_v2 import value_vehicle_v2

SOURCE_AGE_UNKNOWN = "SOURCE_AGE_UNKNOWN"


@dataclass(slots=True)
class HarvestReport:
    market_group_id: str
    queries_attempted: int = 0
    results_returned: int = 0
    listing_candidates: int = 0
    accepted_observations: int = 0
    rejected_observations: int = 0
    duplicate_groups: int = 0
    unique_roi_prices: int = 0
    vat_known: int = 0
    mileage_known: int = 0
    archive_hits: int = 0
    archive_misses: int = 0
    search_requests: int = 0
    elapsed_seconds: float = 0
    stopped_reason: str = ""
    observations: list[MarketObservation] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = {key: getattr(self, key) for key in (
            "market_group_id", "queries_attempted", "results_returned", "listing_candidates",
            "accepted_observations", "rejected_observations", "duplicate_groups", "unique_roi_prices",
            "vat_known", "mileage_known", "archive_hits", "archive_misses", "search_requests",
            "elapsed_seconds", "stopped_reason", "error",
        )}
        return payload


def decision_usable(subject: VehicleIdentity, book: MarketBook, as_of: datetime) -> bool:
    result = value_vehicle_v2(subject, book, as_of=as_of)
    return result.confidence_label in {"MEDIUM", "HIGH"} and result.conservative_eur is not None


async def harvest_group(
    group: MarketGroup,
    *,
    client: httpx.AsyncClient,
    budget: SearchBudget,
    auction_id: str,
    existing: list[MarketObservation] | None = None,
    provider: MarketSearchProvider | None = None,
    enricher: CommonCrawlMarketEnricher | None = None,
    strategies: tuple[str, ...] = ("strategy-1", "strategy-2", "strategy-3"),
    as_of: datetime | None = None,
) -> HarvestReport:
    started = time.perf_counter()
    moment = as_of or datetime.now(timezone.utc)
    report = HarvestReport(group.group_id)
    rows = list(existing or [])
    subject = _subject(group, moment)
    if not search_enabled():
        report.stopped_reason = "SEARCH_DISABLED"
        report.elapsed_seconds = time.perf_counter() - started
        return report
    if not brave_configured() and provider is None:
        report.error = "SEARCH PROVIDER NOT CONFIGURED"
        report.stopped_reason = "NOT_CONFIGURED"
        report.elapsed_seconds = time.perf_counter() - started
        return report
    searcher = provider or BraveMarketSearchProvider(client)
    archive = enricher or CommonCrawlMarketEnricher(client)
    for strategy in strategies:
        if decision_usable(subject, MarketBook(primary_observations(rows)), moment):
            report.stopped_reason = "SUFFICIENT"
            break
        for query in queries_for(group, strategy):
            if not budget.allow(group_id=group.group_id, auction_id=auction_id):
                report.stopped_reason = "BUDGET"
                break
            added = await _run_query(query, searcher, budget, auction_id, archive, report, moment)
            rows.extend(added)
        if report.stopped_reason == "BUDGET":
            break
    if report.stopped_reason not in {"SUFFICIENT", "BUDGET"} and _vat_share(rows) < Decimal("0.25"):
        report.stopped_reason = "VAT_ENRICHMENT"
        for query in vat_queries(group):
            if decision_usable(subject, MarketBook(primary_observations(rows)), moment):
                report.stopped_reason = "SUFFICIENT"
                break
            if not budget.allow(group_id=group.group_id, auction_id=auction_id):
                report.stopped_reason = "BUDGET"
                break
            rows.extend(await _run_query(query, searcher, budget, auction_id, archive, report, moment))
    grouped = assign_duplicate_groups(rows)
    primary = primary_observations(grouped)
    report.observations = primary
    report.duplicate_groups = len({row.cross_source_duplicate_group_id for row in grouped if row.cross_source_duplicate_group_id})
    roi = [row for row in primary if row.geography == "ROI" and row.asking_price_eur]
    report.unique_roi_prices = len(roi)
    report.vat_known = sum(1 for row in roi if row.vat_presentation not in {"", "unknown"})
    report.mileage_known = sum(1 for row in roi if row.mileage_km)
    report.accepted_observations = len(primary)
    if not report.stopped_reason:
        report.stopped_reason = "SUFFICIENT" if decision_usable(subject, MarketBook(primary), moment) else "THIN"
    report.elapsed_seconds = round(time.perf_counter() - started, 3)
    return report


async def _run_query(
    query: SearchQuery,
    searcher: MarketSearchProvider,
    budget: SearchBudget,
    auction_id: str,
    archive: CommonCrawlMarketEnricher,
    report: HarvestReport,
    moment: datetime,
) -> list[MarketObservation]:
    report.queries_attempted += 1
    cached = budget.cached(query.text)
    if cached:
        hits = [_hit(row) for row in cached.get("hits") or []]
    else:
        try:
            response = await searcher.search(query.text)
        except SearchNotConfigured:
            report.error = "SEARCH PROVIDER NOT CONFIGURED"
            return []
        except SearchRejected as exc:
            report.error = str(exc)
            return []
        budget.record(group_id=query.group_id, auction_id=auction_id)
        budget.store(query.text, response)
        report.search_requests += 1
        hits = response.hits
    report.results_returned += len(hits)
    accepted: list[MarketObservation] = []
    for hit in hits[:8]:
        extracted = extract_listing(hit.url, hit.title, hit.description, *hit.extra_snippets)
        if extracted.rejection:
            report.rejected_observations += 1
            continue
        if extracted.price_status == "PRICE_PLAUSIBLE":
            family_status = price_plausible_for_family(extracted.price_eur, query.model_family)
            if family_status != "PRICE_PLAUSIBLE":
                extracted.price_status = family_status
                report.rejected_observations += 1
                continue
        report.listing_candidates += 1
        identity = parse_listing_text(hit.title, hit.description)
        if identity.model_family != query.model_family and not query.adjustment_only:
            report.rejected_observations += 1
            continue
        family = identity.model_family or query.model_family
        capture = await archive.enrich(hit.url)
        if capture.status == "ARCHIVE_MISS":
            report.archive_misses += 1
        else:
            report.archive_hits += 1
        quality = _quality(hit, capture)
        observed = _observed_at(hit, capture, moment)
        accepted.append(
            _observation(query, hit, extracted, family, quality, observed, moment, capture)
        )
    return accepted


def _observation(query, hit, extracted, family, quality, observed, moment, capture: ArchiveCapture) -> MarketObservation:
    listing_id = hashlib.sha256(hit.url.encode("utf-8")).hexdigest()[:24]
    observation_id = f"{query.source_id}-{listing_id}-{int(moment.timestamp())}"
    fuel = Fuel.DIESEL if "diesel" in (hit.title + hit.description).lower() else Fuel.UNKNOWN
    return MarketObservation(
        observation_id=observation_id,
        listing_id=listing_id,
        observed_at=observed,
        manufacturer=query.model_family.split("_")[0],
        model_family=family,
        year=extracted.year,
        fuel=fuel,
        body="PANEL" if extracted.body in {"PANEL", "UNKNOWN"} else extracted.body,
        wheelbase=None,
        roof=None,
        transmission=None,
        derivative=None,
        mileage_km=extracted.mileage_km,
        generation=None,
        asking_price_eur=extracted.price_eur,
        realised_price_eur=None,
        seller_type="dealer",
        vat_presentation=extracted.vat_presentation,
        location=extracted.location,
        status=ObservationStatus.ACTIVE,
        source=query.source_id,
        url=hit.url,
        listing_title=hit.title,
        dealer_name=extracted.dealer,
        vat_classification=extracted.vat_classification,
        vat_fragment=extracted.vat_fragment,
        parser_version="market-extract-1",
        source_type=quality,
        capture_method="search-index" if quality == "SEARCH_INDEX_CURRENT" else "common-crawl",
        evidence_quality=quality,
        source_observed_at=capture.crawl_timestamp,
        geography=extracted.geography,
        price_status=extracted.price_status,
        mileage_evidence=extracted.mileage_evidence,
        price_evidence=extracted.price_evidence,
        listing_class=extracted.listing_class,
        raw_reference=hit.page_age or hit.age or SOURCE_AGE_UNKNOWN,
    )


def _quality(hit: SearchHit, capture: ArchiveCapture) -> str:
    if capture.status in {"ARCHIVE_RECENT", "ARCHIVE_HISTORICAL"} and not (hit.page_age or hit.age):
        return capture.status
    return "SEARCH_INDEX_CURRENT"


def _observed_at(hit: SearchHit, capture: ArchiveCapture, moment: datetime) -> datetime:
    if capture.crawl_timestamp and capture.status == "ARCHIVE_RECENT":
        return capture.crawl_timestamp
    if hit.page_age:
        parsed = _page_age(hit.page_age)
        if parsed:
            return parsed
    return moment


def _page_age(value: str) -> datetime | None:
    text = value.strip()
    if len(text) >= 10 and text[4] == "-":
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _hit(row: dict[str, Any]) -> SearchHit:
    from app.domains.vehicles.market_provider import SearchHit as Hit

    return Hit(
        url=str(row.get("url") or ""),
        title=str(row.get("title") or ""),
        description=str(row.get("description") or ""),
        extra_snippets=tuple(row.get("extra_snippets") or ()),
        page_age=row.get("page_age"),
        age=row.get("age"),
        domain=str(row.get("domain") or ""),
    )


def _subject(group: MarketGroup, moment: datetime) -> VehicleIdentity:
    year = group.year_from + 1
    identity = VehicleIdentity(manufacturer="", model_family=group.model_family, year=year, mileage_km=100_000)
    from app.domains.vehicles.enums import BodyKind

    try:
        identity.body = BodyKind(group.body if group.body in BodyKind.__members__ else "PANEL")
    except ValueError:
        identity.body = BodyKind.PANEL
    identity.fuel = Fuel.DIESEL if group.fuel == "DIESEL" else Fuel.UNKNOWN
    del moment
    return identity


def _vat_share(rows: list[MarketObservation]) -> Decimal:
    priced = [row for row in rows if row.asking_price_eur]
    if not priced:
        return Decimal("0")
    known = sum(1 for row in priced if row.vat_presentation not in {"", "unknown"})
    return Decimal(known) / Decimal(len(priced))


def gap_status(report: HarvestReport) -> str:
    if report.error == "SEARCH PROVIDER NOT CONFIGURED":
        return "NOT_CONFIGURED"
    if report.stopped_reason == "SUFFICIENT":
        return "SUFFICIENT"
    if report.stopped_reason == "VAT_ENRICHMENT":
        return "VAT_ENRICHMENT"
    if report.stopped_reason == "BUDGET" and report.unique_roi_prices < 5:
        return "THIN"
    if report.unique_roi_prices == 0 and report.error:
        return "FAILED"
    if report.unique_roi_prices < 5:
        return "THIN"
    return "STALE"
