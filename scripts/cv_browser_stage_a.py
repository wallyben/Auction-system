"""Stage A public-page harvest for the five DATA-006B vehicles. Prints measured facts only."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.domains.vehicles.browser_market.harvest import harvest_market_group
from app.domains.vehicles.browser_market.playwright_runtime import browser_session, fetch_with_retry, host_lock
from app.domains.vehicles.market import MarketBook
from app.domains.vehicles.market_harvest import decision_usable
from app.domains.vehicles.market_search import group_for
from app.domains.vehicles.valuation_v2 import value_vehicle_v2
from urllib.parse import urlparse

VEHICLES = (
    ("2018 TRANSIT CUSTOM", "transit_custom", 2018),
    ("2019 TRANSIT CONNECT", "transit_connect", 2019),
    ("2021 TRANSIT", "transit", 2021),
    ("2023 PARTNER", "partner", 2023),
    ("2020 COMBO", "combo", 2020),
)


def main() -> None:
    moment = datetime.now(timezone.utc)
    timeout = 30000
    reports = []
    with browser_session(timeout_ms=timeout) as browser:
        def fetch(url: str):
            host = urlparse(url).netloc or "unknown"
            with host_lock(host):
                return fetch_with_retry(browser, url)

        for label, family, year in VEHICLES:
            group = group_for(family, year, "PANEL", "DIESEL")
            assert group is not None
            report = harvest_market_group(group, fetch, as_of=moment, delay_s=1.5)
            from app.domains.vehicles.market_harvest import _subject

            subject = _subject(group, moment)
            valued = value_vehicle_v2(subject, MarketBook(report.observations), as_of=moment)
            reports.append(
                {
                    "vehicle": label,
                    "group": group.group_id,
                    "pages": report.pages_opened,
                    "raw_cards": report.raw_cards,
                    "enriched": report.enriched,
                    "rejected": report.rejected,
                    "unique_roi": report.unique_roi,
                    "mileage_known": report.mileage_known,
                    "vat_known": report.vat_known,
                    "stopped": report.stopped_reason,
                    "decision_usable": decision_usable(subject, MarketBook(report.observations), moment),
                    "confidence": valued.confidence_label,
                    "conservative_resale": str(valued.conservative_eur) if valued.conservative_eur is not None else None,
                    "sources": report.to_dict()["sources"],
                }
            )
            print(json.dumps(reports[-1]), flush=True)
    print(json.dumps({"stage_a": reports}))


if __name__ == "__main__":
    main()
