"""ARIE-CV jobs. They run in the worker, never inside the web process."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.domains.vehicles.board import shadow_count
from app.domains.vehicles.certification_metrics import score_certification
from app.domains.vehicles.history_dvsa import dvsa_status
from app.domains.vehicles.ingest.dealer_feed import PARSER_VERSION as DEALER_PARSER
from app.domains.vehicles.ingest.dealer_feed import parse_dealer_feed
from app.domains.vehicles.ingest.ebay_vans import PARSER_VERSION as EBAY_PARSER
from app.domains.vehicles.ingest.ebay_vans import SOURCE_ID as EBAY_SOURCE
from app.domains.vehicles.ingest.ebay_vans import observations_from_summaries, vans_enabled
from app.domains.vehicles.ingest.mid_ulster import PARSER_VERSION as MID_ULSTER_PARSER
from app.domains.vehicles.runtime_book import add_observations, current_book
from app.domains.vehicles.sources import enabled_live_fetchers
from app.domains.vehicles.store import record_source_state

CV_JOBS = (
    "cv-auction-ingest",
    "cv-market-refresh",
    "cv-history-enrich",
    "cv-revalue",
    "cv-shadow-refresh",
)


async def run_cv_job(session: Session, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if name == "cv-auction-ingest":
        return _auction_ingest(session)
    if name == "cv-market-refresh":
        return await _market_refresh(session, payload)
    if name == "cv-history-enrich":
        return _history_enrich(session)
    if name == "cv-revalue":
        return {"status": "idle", "reason": "Stored cases are revalued when the owner captures a lot or posts /cv/api/evaluate. No autonomous auction book is live."}
    if name == "cv-shadow-refresh":
        return _shadow_refresh(session)
    raise ValueError(f"unknown cv job {name}")


def _auction_ingest(session: Session) -> dict[str, Any]:
    record_source_state(
        session,
        source_id="mid_ulster",
        status="MANUAL_ONLY",
        parser_version=MID_ULSTER_PARSER,
        last_success_at=None,
        last_error="",
        payload={
            "fetcher": "disabled",
            "reason": "Website text may not be copied without written consent. Owner catalogue paste is the ingestion path.",
        },
    )
    return {
        "status": "manual_only",
        "source": "mid_ulster",
        "live_fetchers": list(enabled_live_fetchers()),
        "parser_version": MID_ULSTER_PARSER,
    }


async def _market_refresh(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    inserted = 0
    now = datetime.now(timezone.utc)
    feed_text = str(payload.get("feed_text") or "")
    if feed_text:
        rows = parse_dealer_feed(feed_text, observed_at=now)
        inserted, duplicates = add_observations(rows)
        record_source_state(
            session,
            source_id="dealer_stock_feed",
            status="LIVE_MANUAL",
            parser_version=DEALER_PARSER,
            last_success_at=now,
            last_error="",
            payload={"inserted": inserted, "duplicates": duplicates},
        )
    urls = [part.strip() for part in os.environ.get("CV_DEALER_FEED_URLS", "").split(",") if part.strip()]
    ebay_count = 0
    if vans_enabled():
        summaries = await _ebay_summaries()
        observations = observations_from_summaries(summaries, observed_at=now)
        ebay_count, _duplicates = add_observations(observations)
        record_source_state(
            session,
            source_id=EBAY_SOURCE,
            status="LIVE_AUTHENTICATED",
            parser_version=EBAY_PARSER,
            last_success_at=now,
            last_error="",
            payload={"inserted": ebay_count, "summaries": len(summaries)},
        )
    else:
        record_source_state(
            session,
            source_id=EBAY_SOURCE,
            status="BLOCKED_CREDENTIALS",
            parser_version=EBAY_PARSER,
            last_success_at=None,
            last_error="EBAY_CLIENT_ID / EBAY_CLIENT_SECRET not set, or CV_EBAY_VANS=0.",
            payload={},
        )
    return {
        "status": "ok",
        "dealer_inserted": inserted,
        "ebay_inserted": ebay_count,
        "configured_feed_urls": len(urls),
        "book_size": len(current_book().observations),
        "fetched_remote_feeds": False,
    }


def _history_enrich(session: Session) -> dict[str, Any]:
    status = dvsa_status()
    record_source_state(
        session,
        source_id="dvsa_mot",
        status=str(status["status"]),
        parser_version="dvsa-mot-1",
        last_success_at=None,
        last_error="" if status["status"] == "CONFIGURED" else "credentials missing",
        payload=status,
    )
    return {"status": status["status"], "missing_env": status["missing_env"]}


def _shadow_refresh(session: Session) -> dict[str, Any]:
    live = enabled_live_fetchers()
    report = score_certification(historical_cases=0, live_shadow_cases=shadow_count() if live else 0)
    record_source_state(
        session,
        source_id="cv_shadow",
        status=str(report["posture"]),
        parser_version="shadow-1",
        last_success_at=datetime.now(timezone.utc),
        last_error="",
        payload=report,
    )
    return report


async def _ebay_summaries() -> list[dict[str, Any]]:
    from app.core.config import settings
    from app.core.http import build_client, request_json
    from app.sources.ebay import SEARCH_URL, EbayBrowseAdapter

    adapter = EbayBrowseAdapter()
    headers = await adapter._token_header()
    found: list[dict[str, Any]] = []
    markets = [market for market in ("EBAY_IE", "EBAY_GB") if market in set(settings.ebay_marketplace_list())]
    markets = markets or ["EBAY_IE"]
    from app.domains.vehicles.ingest.ebay_vans import VAN_QUERIES

    async with build_client() as client:
        for market in markets:
            headers["X-EBAY-C-MARKETPLACE-ID"] = market
            for query in VAN_QUERIES[:2]:
                _response, payload = await request_json(
                    client,
                    "GET",
                    SEARCH_URL[settings.ebay_api_env],
                    headers=headers,
                    params={"q": query, "limit": "10"},
                )
                found.extend(payload.get("itemSummaries") or [])
    return found
