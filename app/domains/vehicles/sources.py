"""Irish and NI commercial-vehicle sources. Each adapter is independently off.

No source here is LIVE. Manual capture is the only ingest that does not need
an external credential or a terms decision. Nothing in this module fetches HTML.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VehicleSource:
    source_id: str
    name: str
    geography: str
    role: str
    status: str
    access: str
    reason: str
    buyer_premium: str
    vat: str
    registration_visible: str
    vin_visible: str
    results_available: str

    def to_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "geography": self.geography,
            "role": self.role,
            "status": self.status,
            "access": self.access,
            "reason": self.reason,
            "buyer_premium": self.buyer_premium,
            "vat": self.vat,
            "registration_visible": self.registration_visible,
            "vin_visible": self.vin_visible,
            "results_available": self.results_available,
        }


def vehicle_sources() -> tuple[VehicleSource, ...]:
    return (
        VehicleSource(
            source_id="cv_manual",
            name="Owner manual capture",
            geography="IE/NI",
            role="acquisition_and_market",
            status="LIVE_MANUAL",
            access="Structured input supplied by the owner. No crawl.",
            reason="Permitted fallback. The owner pastes a listing they are allowed to record.",
            buyer_premium="Must be entered per catalogue. Not assumed.",
            vat="Must be entered. Not assumed.",
            registration_visible="Only if the owner records it.",
            vin_visible="Only if the owner records it.",
            results_available="Only if the owner records an outcome.",
        ),
        VehicleSource(
            source_id="wilsons",
            name="Wilsons Auctions",
            geography="IE and NI",
            role="acquisition",
            status="BLOCKED_POLICY",
            access="Public catalogue pages exist. No official public API was found.",
            reason="Existing ARIE policy refuses unofficial scraping. A plant-auction fee note is not a van fee schedule.",
            buyer_premium="Catalogue-specific. Not loaded.",
            vat="Lot-specific. Not loaded.",
            registration_visible="Varies by lot. Not verified in an API.",
            vin_visible="Varies by lot. Not verified in an API.",
            results_available="Not ingested.",
        ),
        VehicleSource(
            source_id="copart_ie",
            name="Copart Ireland",
            geography="IE",
            role="acquisition",
            status="BLOCKED_CREDENTIALS",
            access="Trade membership. Fees published to members and change by volume.",
            reason="No member credential is configured. Terms forbid treating guest pages as a feed.",
            buyer_premium="Member schedule. Not loaded.",
            vat="Fees quoted ex VAT. Lot VAT varies.",
            registration_visible="Member lot pages. Not ingested.",
            vin_visible="Often present for salvage. Not ingested.",
            results_available="Member history. Not ingested.",
        ),
        VehicleSource(
            source_id="bca",
            name="BCA",
            geography="GB/NI",
            role="acquisition",
            status="BLOCKED_CREDENTIALS",
            access="Buyer login. No public developer API used by ARIE.",
            reason="Authentication would be required. ARIE will not use a shared password or bypass a login.",
            buyer_premium="Account-specific. Not loaded.",
            vat="Lot-specific. Not loaded.",
            registration_visible="Usually behind login.",
            vin_visible="Usually behind login.",
            results_available="Not ingested.",
        ),
        VehicleSource(
            source_id="manheim",
            name="Manheim",
            geography="GB/NI",
            role="acquisition",
            status="BLOCKED_CREDENTIALS",
            access="Buyer login.",
            reason="No credential and no permitted feed configured.",
            buyer_premium="Not loaded.",
            vat="Not loaded.",
            registration_visible="Behind login.",
            vin_visible="Behind login.",
            results_available="Not ingested.",
        ),
        VehicleSource(
            source_id="dvsa_mot",
            name="DVSA MOT history",
            geography="GB/NI",
            role="history",
            status="BLOCKED_CREDENTIALS",
            access="Official MOT History API. Requires a registered key.",
            reason="No DVSA key is configured. The check is not pretended to have been run.",
            buyer_premium="n/a",
            vat="n/a",
            registration_visible="API can take a registration.",
            vin_visible="API can return a VIN where DVSA holds one.",
            results_available="MOT tests, when a key exists.",
        ),
        VehicleSource(
            source_id="cartell_motorcheck",
            name="Cartell / Motorcheck",
            geography="IE",
            role="history",
            status="BLOCKED_CREDENTIALS",
            access="Paid Irish vehicle-history reports.",
            reason="Paid Irish vehicle-history reports. The owner can buy a trade subscription. No key is configured, so finance, write-off, and stolen results are not inferred.",
            buyer_premium="n/a",
            vat="n/a",
            registration_visible="Report-specific.",
            vin_visible="Report-specific.",
            results_available="Not ingested.",
        ),
        VehicleSource(
            source_id="donedeal",
            name="DoneDeal",
            geography="IE",
            role="market",
            status="BLOCKED_POLICY",
            access="Dealer API is partner-only. Public pages are not scraped.",
            reason="Same policy as the existing ARIE source register.",
            buyer_premium="n/a",
            vat="Listing-specific. Not ingested.",
            registration_visible="Often hidden.",
            vin_visible="Rarely public.",
            results_available="Disappearance is not a sale, and it is not ingested.",
        ),
        VehicleSource(
            source_id="adverts_ie",
            name="Adverts.ie",
            geography="IE",
            role="market",
            status="BLOCKED_POLICY",
            access="No official public aggregation API.",
            reason="Unofficial wrappers are not used.",
            buyer_premium="n/a",
            vat="Not ingested.",
            registration_visible="Varies.",
            vin_visible="Rare.",
            results_available="Not ingested.",
        ),
        VehicleSource(
            source_id="carzone",
            name="Carzone",
            geography="IE",
            role="market",
            status="BLOCKED_POLICY",
            access="Dealer inventory site. No licensed feed configured.",
            reason="Not scraped. Owner CSV of observations the owner is entitled to record is the fallback.",
            buyer_premium="n/a",
            vat="Dealer VAT presentation varies.",
            registration_visible="Varies.",
            vin_visible="Rare.",
            results_available="Not ingested.",
        ),
        VehicleSource(
            source_id="mid_ulster",
            name="Mid Ulster Auctions (Dulster)",
            geography="NI",
            role="acquisition",
            status="MANUAL_ONLY",
            access="Owner pastes or uploads the catalogue they are using. ARIE does not download the website.",
            reason=(
                "Public catalogues exist and robots.txt allows a slow crawl except /login, /signup, and /search. "
                "The terms say website text may not be copied without written consent, so unattended ingestion is not enabled. "
                "The owner-capture parser reads lot id, title, registration, year, mileage, VAT, vendor, documents, MOT/PSV, bid, and close time when those lines are in the paste."
            ),
            buyer_premium="Parsed only from the Cars, Vans bands in the supplied catalogue. Otherwise unknown.",
            vat="Lot VAT Yes/No when printed. Premium VAT only when the catalogue says plus VAT. UK 20%, not Irish 23%.",
            registration_visible="When the catalogue line Serial/Reg# is present.",
            vin_visible="Not in the public lot summary. Owner document required.",
            results_available="Not inferred from a closed catalogue. A realised price must be entered as a realised observation.",
        ),
        VehicleSource(
            source_id="dealer_stock_feed",
            name="Owner-consented dealer stock feed",
            geography="IE",
            role="market",
            status="BLOCKED_CREDENTIALS",
            access="CSV or JSON the owner is allowed to store, or CV_DEALER_FEED_URLS for feeds the owner is permitted to pull.",
            reason="DoneDeal, Carzone, CarsIreland, and Adverts do not allow multi-dealer aggregation. A consented single-dealer feed is the lawful market path.",
            buyer_premium="n/a",
            vat="Taken from the feed column when present. Not guessed.",
            registration_visible="Only if the feed includes it.",
            vin_visible="Only if the feed includes it.",
            results_available="Disappearance is stored and is not treated as a sale.",
        ),
        VehicleSource(
            source_id="ebay_motors",
            name="eBay Motors",
            geography="IE/GB/NI",
            role="acquisition_and_market",
            status="DISABLED",
            access="Official Browse API already exists for the camera pipeline.",
            reason="The camera Browse adapter is not used for vans. A separate van search runs only when EBAY_CLIENT_ID and EBAY_CLIENT_SECRET are set and CV_EBAY_VANS is not 0.",
            buyer_premium="n/a",
            vat="Listing-specific.",
            registration_visible="Varies.",
            vin_visible="Varies.",
            results_available="Sold evidence is not reused from camera queries.",
        ),
    )


def enabled_live_fetchers() -> tuple[str, ...]:
    """Network fetchers ARIE-CV may call. Empty unless a permitted credential exists."""

    import os

    live: list[str] = []
    if os.environ.get("EBAY_CLIENT_ID", "").strip() and os.environ.get("EBAY_CLIENT_SECRET", "").strip():
        if os.environ.get("CV_EBAY_VANS", "1") != "0":
            live.append("ebay_vans")
    if os.environ.get("CV_DEALER_FEED_URLS", "").strip():
        live.append("dealer_stock_feed")
    return tuple(live)
