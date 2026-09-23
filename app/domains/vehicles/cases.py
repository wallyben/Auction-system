"""Inputs to a commercial-vehicle evaluation. Missing fields stay unknown."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.domains.vehicles.auction_costs import AuctionFeeSchedule
from app.domains.vehicles.enums import AuctionVatTreatment, Co2Basis, EvidencePosture, Fuel
from app.domains.vehicles.history import HistoryInput
from app.domains.vehicles.identity import ListingIdentity, VehicleIdentity
from app.domains.vehicles.market import MarketBook
from app.domains.vehicles.provenance import ProvenanceInput
from app.domains.vehicles.tax import Homologation


@dataclass(slots=True)
class VehicleCase:
    listing: ListingIdentity
    identity: VehicleIdentity
    as_of: datetime
    provenance: ProvenanceInput = field(default_factory=ProvenanceInput)
    history: HistoryInput = field(default_factory=lambda: HistoryInput(listing_mileage_km=None))
    book: MarketBook = field(default_factory=MarketBook)
    homologation: Homologation | None = None
    co2_g_per_km: Decimal | None = None
    co2_basis: Co2Basis = Co2Basis.UNKNOWN
    nox_mg_per_km: Decimal | None = None
    omsp_eur: Decimal | None = None
    omsp_source: str | None = None
    schedule: AuctionFeeSchedule | None = None
    vat_treatment: AuctionVatTreatment = AuctionVatTreatment.UNKNOWN
    hammer_includes_vat: bool | None = None
    owner_vat_registered: bool = False
    commercial_vat_invoice_expected: bool = False
    transport_eur: Decimal | None = None
    transport_posture: EvidencePosture = EvidencePosture.UNKNOWN
    border_transport_eur: Decimal | None = None
    insurance_eur: Decimal | None = None
    payment_fee_eur: Decimal | None = None
    payment_fee_posture: EvidencePosture = EvidencePosture.UNKNOWN
    duty_rate: Decimal | None = None
    preferential_origin_proven: bool = False
    registration_fee_eur: Decimal | None = None
    registration_fee_posture: EvidencePosture = EvidencePosture.UNKNOWN
    fx_eur_per_unit: Decimal | None = None
    fx_retrieved_at: datetime | None = None
    mechanical_inspected: bool = False
    fuel_override: Fuel | None = None
    auction_lot_vat_rate: Decimal | None = None
    owner_documents: tuple[object, ...] = ()
