"""Value a listing URL or owner-supplied capture through the production pipeline."""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.pipeline.service import _comps_for, evaluate_listing, persist_listing, refresh_fx
from app.security.ssrf import assert_public_url
from app.sources.base import NormalizedListing
from app.sources.ebay import EbayBrowseAdapter
from app.sources.registry import adapter_map
from app.sources.scryfall import ScryfallAdapter


async def value_url(session: Session, url: str) -> object:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in {"api.scryfall.com", "scryfall.com"}:
        assert_public_url(url)
        slug = parsed.path.rstrip("/").split("/")[-1].replace("-", " ")
        items = await ScryfallAdapter().search(slug, limit=1)
        if not items:
            raise ValueError("Scryfall URL produced no card.")
        item = items[0]
    elif "ebay." in host:
        assert_public_url(url)
        adapter = EbayBrowseAdapter()
        # Browse fetch needs an item id; owner can still paste if credentials work.
        item_id = parsed.path.rstrip("/").split("/")[-1]
        item = await adapter.fetch_listing(item_id)
        if item is None:
            raise ValueError("eBay retrieval failed. Check credentials or use owner capture.")
    else:
        raise ValueError(
            "Automatic retrieval is not allowed for this host. Use Value this item and paste the fields."
        )
    rates = await refresh_fx(session)
    listing = persist_listing(session, item)
    comps = await _comps_for(listing, rates, session)
    from app.sold.certify import live_camera_body_certification

    return evaluate_listing(session, listing, comps, rates, live_cert=live_camera_body_certification(session))


async def value_manual(
    session: Session,
    *,
    title: str,
    description: str = "",
    asking: Decimal | None,
    country: str = "IE",
    currency: str = "EUR",
    url: str = "",
    condition: str = "",
    source_id: str = "manual",
) -> object:
    item = NormalizedListing(
        source_id=source_id if source_id in adapter_map() else "manual",
        external_id=(url or title)[:80],
        url=url or f"manual://{title[:40]}",
        title=title,
        description=description,
        country=country[:2].upper(),
        currency=currency[:3].upper(),
        asking_price=asking,
        condition_raw=condition,
        extras={"owner_capture": True},
        source_confidence=Decimal("0.95"),
    )
    rates = await refresh_fx(session)
    listing = persist_listing(session, item)
    comps = await _comps_for(listing, rates, session)
    from app.sold.certify import live_camera_body_certification

    return evaluate_listing(session, listing, comps, rates, live_cert=live_camera_body_certification(session))
