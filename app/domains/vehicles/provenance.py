"""Northern Ireland / GB / ROI provenance. Auction location is not customs status."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from app.domains.vehicles.enums import EvidencePosture, ProvenanceState, RegistrationSignal
from app.domains.vehicles.evidence import EvidenceLedger, EvidenceRecord

NI_CUTOFF = datetime(2021, 1, 1, tzinfo=timezone.utc)

REVENUE_NI_URL = "https://www.revenue.ie/en/vrt/registration-of-imported-used-vehicles/registering-vehicles-from-ni.aspx"
REVENUE_GB_NI_URL = "https://www.revenue.ie/en/vrt/registration-of-imported-used-vehicles/index.aspx"


@dataclass(frozen=True, slots=True)
class KeeperEvidence:
    """Seller-supplied or register-supplied keeper geography."""

    jurisdiction: str
    resident_in: str
    document: str
    issued_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class HistoryPoint:
    jurisdiction: str
    observed_at: datetime
    kind: str
    reference: str


@dataclass(frozen=True, slots=True)
class ProvenanceInput:
    registration_signal: RegistrationSignal = RegistrationSignal.UNKNOWN
    irish_registration_certificate: bool = False
    irish_registration_reference: str | None = None
    v5c_original: KeeperEvidence | None = None
    ni_import_declaration_reference: str | None = None
    ni_import_declaration_vin: str | None = None
    vehicle_vin: str | None = None
    ni_service_references: tuple[str, ...] = ()
    history: tuple[HistoryPoint, ...] = ()
    auction_country: str | None = None


@dataclass(frozen=True, slots=True)
class ProvenanceResult:
    state: ProvenanceState
    customs_clear: bool
    owner_action: str | None
    interpretation: str


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def assess_provenance(data: ProvenanceInput, ledger: EvidenceLedger) -> ProvenanceResult:
    """Tax-clear NI status requires Revenue's evidence bundle, not a plate or a sale yard."""

    if data.auction_country and data.auction_country.upper() in {"NI", "GB", "UK", "IE"}:
        ledger.add(
            EvidenceRecord(
                field="auction_country",
                posture=EvidencePosture.PROVEN,
                status=data.auction_country.upper(),
                confidence=Decimal("1"),
                source="listing",
                interpretation="Auction geography is recorded. It does not establish customs status.",
                blocking=False,
            )
        )

    if data.irish_registration_certificate:
        ledger.add(
            EvidenceRecord(
                field="irish_registration",
                posture=EvidencePosture.PROVEN,
                status="CERTIFICATE",
                confidence=Decimal("0.95"),
                source="irish_registration_certificate",
                interpretation="An Irish registration certificate was supplied for this vehicle.",
                blocking=False,
                raw_reference=data.irish_registration_reference,
                source_url=REVENUE_GB_NI_URL,
            )
        )
        return ProvenanceResult(
            state=ProvenanceState.ROI_NATIVE,
            customs_clear=True,
            owner_action=None,
            interpretation="Irish registration certificate supplied. No import VAT or customs duty is modelled.",
        )

    declaration_matches = bool(
        data.ni_import_declaration_reference
        and data.ni_import_declaration_vin
        and data.vehicle_vin
        and data.ni_import_declaration_vin == data.vehicle_vin
    )
    if declaration_matches:
        ledger.add(
            EvidenceRecord(
                field="ni_import_declaration",
                posture=EvidencePosture.PROVEN,
                status="VIN_MATCH",
                confidence=Decimal("0.95"),
                source="ni_import_declaration",
                interpretation="NI import declaration identifies this VIN.",
                blocking=False,
                raw_reference=data.ni_import_declaration_reference,
                source_url=REVENUE_NI_URL,
            )
        )
        return ProvenanceResult(
            state=ProvenanceState.NI_POST_2020_IMPORT_PROVEN,
            customs_clear=True,
            owner_action=None,
            interpretation=(
                "Windsor Framework NI import declaration tied to the VIN. "
                "Customs duty and import VAT are not modelled. VRT still is."
            ),
        )

    v5c_ni = bool(
        data.v5c_original
        and data.v5c_original.document == "V5C"
        and data.v5c_original.jurisdiction == "NI"
        and data.v5c_original.resident_in == "NI"
    )
    ni_history = [point for point in data.history if point.jurisdiction == "NI"]
    gb_history = [point for point in data.history if point.jurisdiction == "GB"]
    has_service = len(data.ni_service_references) > 0
    has_mot = any(point.kind == "MOT" for point in ni_history)
    pre_2021 = any(_aware(point.observed_at) < NI_CUTOFF for point in ni_history)

    if data.v5c_original and data.v5c_original.jurisdiction == "GB":
        ledger.add(
            EvidenceRecord(
                field="v5c",
                posture=EvidencePosture.PROVEN,
                status="GB_KEEPER",
                confidence=Decimal("0.9"),
                source="v5c",
                interpretation="Original V5C shows a GB keeper. NI sale location does not clear customs.",
                blocking=True,
                source_url=REVENUE_GB_NI_URL,
            )
        )
        return ProvenanceResult(
            state=ProvenanceState.GB_TO_NI_UNPROVEN if data.registration_signal is RegistrationSignal.NI_FORMAT_WEAK or data.auction_country == "NI" else ProvenanceState.GB_ORIGIN,
            customs_clear=False,
            owner_action="Treat as a GB import unless an NI import declaration tied to this VIN is produced.",
            interpretation="GB keeper on the V5C. Customs duty and import VAT may arise. They are not waived.",
        )

    if v5c_ni and has_service and has_mot and pre_2021 and not gb_history:
        ledger.add(
            EvidenceRecord(
                field="ni_provenance_bundle",
                posture=EvidencePosture.PROVEN,
                status="PRE_2021_BUNDLE",
                confidence=Decimal("0.8"),
                source="v5c+ni_service+ni_mot",
                interpretation=(
                    "Original NI V5C, NI service history, and NI MOT history with a pre-2021 NI test. "
                    "Revenue may still verify the bundle."
                ),
                blocking=False,
                source_url=REVENUE_NI_URL,
            )
        )
        return ProvenanceResult(
            state=ProvenanceState.NI_PRE_2021_PROVEN,
            customs_clear=True,
            owner_action="Take the original V5C, NI service history, and NI MOT printout to NCTS. Revenue verifies the bundle.",
            interpretation="Pre-2021 NI evidence bundle present. Customs duty and import VAT are not modelled. VRT still is.",
        )

    if v5c_ni or data.registration_signal is RegistrationSignal.NI_FORMAT_WEAK or ni_history:
        ledger.add(
            EvidenceRecord(
                field="ni_provenance_bundle",
                posture=EvidencePosture.UNKNOWN,
                status="INCOMPLETE",
                confidence=Decimal("0.3"),
                source="partial_ni_signal",
                interpretation="NI signals exist but the Revenue evidence bundle or import declaration is incomplete.",
                blocking=True,
                source_url=REVENUE_NI_URL,
            )
        )
        return ProvenanceResult(
            state=ProvenanceState.LIKELY_NI_NEEDS_DOCUMENTS,
            customs_clear=False,
            owner_action=(
                "Obtain the original V5C showing an NI keeper, NI service history, and NI MOT history. "
                "If the vehicle entered NI after 31 December 2020, obtain the NI Import Declaration tied to this VIN."
            ),
            interpretation="Northern Ireland is plausible and unproven. Customs status fails closed.",
        )

    if data.registration_signal is RegistrationSignal.GB_FORMAT or gb_history:
        return ProvenanceResult(
            state=ProvenanceState.GB_ORIGIN,
            customs_clear=False,
            owner_action="Complete an Irish customs declaration. Duty depends on origin proof and the TARIC code. Import VAT is due on the customs value plus duty.",
            interpretation="GB origin. Import formalities apply. A GB plate is not an NI customs exemption.",
        )

    ledger.add(
        EvidenceRecord(
            field="provenance",
            posture=EvidencePosture.UNKNOWN,
            status="UNKNOWN",
            confidence=Decimal("0"),
            source="",
            interpretation="No registration certificate, V5C, MOT geography, or import declaration was supplied.",
            blocking=True,
            source_url=REVENUE_GB_NI_URL,
        )
    )
    return ProvenanceResult(
        state=ProvenanceState.UNKNOWN,
        customs_clear=False,
        owner_action="Establish whether the vehicle is already Irish-registered, NI-proven, or a GB/third-country import before bidding.",
        interpretation="Provenance unknown. Import VAT and customs duty are not assumed to be zero.",
    )
