"""ECB euro foreign-exchange reference rates."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal
from xml.etree import ElementTree

from app.core.http import build_client, request_json
from app.core.logging import get_logger
from app.models.enums import SourceKind, SourceStatus
from app.sources.base import HealthProof, NormalizedListing, SourceAdapter

logger = get_logger("arie.sources.ecb")
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
NS = {"e": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}


class EcbFxAdapter(SourceAdapter):
    source_id = "ecb_fx"
    display_name = "ECB euro FX reference"
    country = "EU"
    kind = SourceKind.FX
    official_api = True
    access_method = "official_xml"
    credentials_required = False
    cadence_minutes = 360

    async def healthcheck(self) -> HealthProof:
        started = time.perf_counter()
        try:
            rates, as_of = await self.fetch_rates()
            return HealthProof(
                status=SourceStatus.LIVE,
                ok="GBP" in rates,
                http_status=200,
                latency_ms=int((time.perf_counter() - started) * 1000),
                records=len(rates),
                detail=f"ECB daily FX as of {as_of.date().isoformat()}",
                proof={"as_of": as_of.isoformat(), "gbp": str(rates.get("GBP")), "usd": str(rates.get("USD"))},
            )
        except Exception as exc:
            logger.warning("ecb_health_failed", error=str(exc))
            return HealthProof(
                status=SourceStatus.BLOCKED_TECHNICAL,
                ok=False,
                http_status=None,
                latency_ms=int((time.perf_counter() - started) * 1000),
                records=0,
                detail=str(exc),
                proof={},
            )

    async def search(self, query: str, *, limit: int = 20) -> list[NormalizedListing]:
        return []

    async def fetch_rates(self) -> tuple[dict[str, Decimal], datetime]:
        async with build_client() as client:
            response, payload = await request_json(client, "GET", ECB_URL)
        xml = payload if isinstance(payload, str) else response.text
        root = ElementTree.fromstring(xml)
        cube_time = root.find(".//e:Cube[@time]", NS)
        as_of = (
            datetime.fromisoformat(cube_time.attrib["time"]).replace(tzinfo=timezone.utc)
            if cube_time is not None
            else datetime.now(timezone.utc)
        )
        rates: dict[str, Decimal] = {"EUR": Decimal("1")}
        for cube in root.findall(".//e:Cube[@currency]", NS):
            rates[cube.attrib["currency"]] = Decimal(cube.attrib["rate"])
        return rates, as_of

    def eur_per_unit(self, rates: dict[str, Decimal], currency: str) -> Decimal:
        currency = currency.upper()
        if currency == "EUR":
            return Decimal("1")
        units_per_eur = rates.get(currency)
        if not units_per_eur:
            raise ValueError(f"No ECB rate for {currency}")
        return Decimal("1") / units_per_eur
