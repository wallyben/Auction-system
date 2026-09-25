"""Replay the DATA-006C browser cache under v2 and v3. Does not open Carzone."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from urllib.parse import urlparse

from app.domains.vehicles.browser_market.base import PageFetch
from app.domains.vehicles.browser_market.harvest import harvest_market_group
from app.domains.vehicles.browser_market.playwright_runtime import browser_session, fetch_with_retry, host_lock
from app.domains.vehicles.market import MarketBook
from app.domains.vehicles.market_harvest import _subject
from app.domains.vehicles.market_search import group_for
from app.domains.vehicles.valuation_v2 import value_vehicle_v2
from app.domains.vehicles.valuation_v3 import value_vehicle_v3

VEHICLES = (
    ("2018 TRANSIT CUSTOM", "transit_custom", 2018),
    ("2019 TRANSIT CONNECT", "transit_connect", 2019),
    ("2021 TRANSIT", "transit", 2021),
    ("2023 PARTNER", "partner", 2023),
    ("2020 COMBO", "combo", 2020),
)
AS_OF = datetime(2026, 9, 24, 22, 0, tzinfo=timezone.utc)


def main() -> None:
    calls = {"network": 0}
    moment = datetime.now(timezone.utc)
    rows = []
    with browser_session(timeout_ms=30000) as browser:
        def fetch(url: str) -> PageFetch:
            if "donedeal.ie" in url or "carsireland.ie" in url:
                return PageFetch(url, url, 403, "", challenge="BLOCKED_CHALLENGE")
            calls["network"] += 1
            host = urlparse(url).netloc or "carzone.ie"
            with host_lock(host):
                return fetch_with_retry(browser, url)

        for label, family, year in VEHICLES:
            group = group_for(family, year, "PANEL", "DIESEL")
            assert group is not None
            report = harvest_market_group(group, fetch, as_of=moment, delay_s=1.2)
            book = MarketBook(report.observations)
            subject = _subject(group, moment)
            v2 = value_vehicle_v2(subject, book, as_of=moment)
            v3 = value_vehicle_v3(subject, book, as_of=moment)
            rows.append(
            {
                "vehicle": label,
                "unique_comps": report.unique_roi,
                "mileage_known": report.mileage_known,
                "vat_known": report.vat_known,
                "v2_confidence": v2.confidence_label,
                "v2_conservative": str(v2.conservative_eur) if v2.conservative_eur is not None else None,
                "v3_market_floor_confidence": v3.market_floor_confidence,
                "v3_vat_confidence": v3.vat_basis_confidence,
                "cash_low": str(v3.market_cash_low_eur) if v3.market_cash_low_eur is not None else None,
                "cash_central_low": str(v3.market_cash_central_low_eur) if v3.market_cash_central_low_eur is not None else None,
                "cash_central_high": str(v3.market_cash_central_high_eur) if v3.market_cash_central_high_eur is not None else None,
                "cash_high": str(v3.market_cash_high_eur) if v3.market_cash_high_eur is not None else None,
                "expected_low": str(v3.expected_achievable_low_eur) if v3.expected_achievable_low_eur is not None else None,
                "expected_high": str(v3.expected_achievable_high_eur) if v3.expected_achievable_high_eur is not None else None,
                "conservative_resale_floor": str(v3.conservative_eur) if v3.conservative_eur is not None else None,
                "vat_stress_proceeds": str(v3.vat_stress_proceeds_eur) if v3.vat_stress_proceeds_eur is not None else None,
                "prebid_floor": "YES" if v3.prebid_floor_available else "NO",
                "used_comps": v3.comparable_count,
                "stopped": report.stopped_reason,
            }
            )
            print(json.dumps(rows[-1]), flush=True)
    print(json.dumps({"network_fetches": calls["network"], "stage_a_v3": rows}))


if __name__ == "__main__":
    main()
