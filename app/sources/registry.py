"""Source registry. Adapters are honest about LIVE vs blocked."""

from __future__ import annotations

from app.models.enums import SourceStatus
from app.sources.base import SourceAdapter
from app.sources.compsniper import CompSniperAdapter
from app.sources.ebay import EbayBrowseAdapter
from app.sources.ecb import EcbFxAdapter
from app.sources.manual import BlockedAdapter, CsvImportAdapter, ManualAdapter
from app.sources.reverb import ReverbAdapter
from app.sources.rss import RssAdapter
from app.sources.scryfall import ScryfallAdapter

POLICY = (
    "No official public aggregation API. ARIE will not scrape or use unofficial clients. "
    "Fallback: owner CSV / manual capture."
)


def _blocked(
    source_id: str,
    name: str,
    country: str,
    extra: str,
    status: SourceStatus = SourceStatus.BLOCKED_POLICY,
) -> BlockedAdapter:
    return BlockedAdapter(
        source_id=source_id,
        display_name=name,
        country=country,
        reason=f"{extra} {POLICY}",
        status=status,
        fallback="csv_import+manual",
    )


def all_adapters() -> list[SourceAdapter]:
    return [
        ReverbAdapter(),
        ScryfallAdapter(),
        EcbFxAdapter(),
        EbayBrowseAdapter(),
        CompSniperAdapter(),
        CsvImportAdapter(),
        ManualAdapter(),
        _blocked("donedeal", "DoneDeal", "IE", "Dealer API is not licensed for multi-dealer aggregation."),
        _blocked("adverts_ie", "Adverts.ie", "IE", "No official public API; unofficial wrappers are not used."),
        _blocked("wilsons", "Wilsons Auctions Ireland", "IE", "No official public catalogue API found."),
        _blocked("john_pye", "John Pye Auctions", "GB", "In-house bidding platform; no public developer API."),
        _blocked("bpi_auctions", "BPI Auctions", "GB", "No official public API found."),
        _blocked("bidspotter", "BidSpotter", "GB", "No official public developer API found."),
        _blocked("i_bidder", "i-bidder", "GB", "No official public developer API found."),
        _blocked("cex_ie", "CeX Ireland", "IE", "No official valuation API. Do not scrape storefront."),
        _blocked(
            "discogs_market",
            "Discogs Marketplace",
            "EU",
            "Marketplace search requires authentication.",
            SourceStatus.BLOCKED_CREDENTIALS,
        ),
        _blocked(
            "cardmarket",
            "Cardmarket",
            "EU",
            "Official API requires owner keys.",
            SourceStatus.BLOCKED_CREDENTIALS,
        ),
        _blocked("kleinanzeigen", "Kleinanzeigen", "DE", "No licensed public API for aggregation."),
        _blocked("leboncoin", "Leboncoin", "FR", "Partner API only."),
        _blocked("marktplaats", "Marktplaats", "NL", "No licensed public aggregation API."),
        _blocked("subito", "Subito", "IT", "No licensed public aggregation API."),
        _blocked("wallapop", "Wallapop", "ES", "No licensed public aggregation API."),
        _blocked(
            "allegro",
            "Allegro",
            "PL",
            "Official REST API exists but requires owner app credentials.",
            SourceStatus.BLOCKED_CREDENTIALS,
        ),
        _blocked("vinted", "Vinted", "EU", "No licensed public aggregation API."),
        _blocked("bstock", "B-Stock", "EU", "Partner API required.", SourceStatus.BLOCKED_CREDENTIALS),
        RssAdapter(),
    ]


def adapter_map() -> dict[str, SourceAdapter]:
    return {adapter.source_id: adapter for adapter in all_adapters()}
