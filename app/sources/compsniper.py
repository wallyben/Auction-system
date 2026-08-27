"""CompSniper is a sold-evidence provider, not an acquisition source."""

from __future__ import annotations

from app.evidence.providers.compsniper import compsniper_health
from app.models.enums import SourceKind, SourceStatus
from app.sources.base import HealthProof, NormalizedListing, SourceAdapter


class CompSniperAdapter(SourceAdapter):
    source_id = "compsniper"
    display_name = "CompSniper completed eBay sales"
    country = "GB"
    kind = SourceKind.REFERENCE
    official_api = True
    access_method = "REST Bearer API (https://api.compsniper.com/v1/scrape)"
    credentials_required = True
    cadence_minutes = 360

    async def healthcheck(self) -> HealthProof:
        payload = compsniper_health()
        status_name = str(payload.get("status") or "DISABLED")
        try:
            status = SourceStatus(status_name)
        except ValueError:
            status = SourceStatus.DISABLED
        return HealthProof(
            status=status,
            ok=status is SourceStatus.LIVE,
            http_status=payload.get("last_http_status") if isinstance(payload.get("last_http_status"), int) else None,
            latency_ms=None,
            records=0,
            detail=str(payload.get("last_error") or status_name),
            proof=payload,
        )

    async def search(self, query: str, *, limit: int = 20) -> list[NormalizedListing]:
        return []
