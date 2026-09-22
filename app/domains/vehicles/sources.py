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
            status="BLOCKED_EXTERNAL",
            access="Paid Irish vehicle-history reports.",
            reason="No paid subscription is configured. Finance, write-off, and stolen results are not inferred.",
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
            source_id="ebay_motors",
            name="eBay Motors",
            geography="IE/GB/NI",
            role="acquisition_and_market",
            status="DISABLED",
            access="Official Browse API already exists for the camera pipeline.",
            reason="The live eBay adapter is camera-filtered and is not certified for vans. It is not called from ARIE-CV.",
            buyer_premium="n/a",
            vat="Listing-specific.",
            registration_visible="Varies.",
            vin_visible="Varies.",
            results_available="Sold evidence is not reused from camera queries.",
        ),
    )


def enabled_live_fetchers() -> tuple[str, ...]:
    """Network fetchers that ARIE-CV is willing to call. Intentionally empty."""

    return ()
