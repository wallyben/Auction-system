"""Owner-supplied documents. A note cannot pass a gate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domains.vehicles.cases import VehicleCase
from app.domains.vehicles.enums import EvidencePosture
from app.domains.vehicles.evidence import EvidenceLedger, EvidenceRecord
from app.domains.vehicles.provenance import KeeperEvidence
from app.domains.vehicles.tax import Homologation

DOCUMENT_KINDS = (
    "V5C",
    "COC",
    "NI_IMPORT_DECLARATION",
    "AUCTION_INVOICE",
    "SERVICE_RECORD",
    "HISTORY_REPORT",
    "WEIGHT_PLATE",
    "VIN",
    "VEHICLE_PHOTOS",
)


@dataclass(frozen=True, slots=True)
class OwnerDocument:
    kind: str
    reference: str
    vehicle_key: str | None = None
    jurisdiction: str | None = None
    resident_in: str | None = None
    issued_at: datetime | None = None
    vin: str | None = None
    eu_category: str | None = None
    seats: int | None = None
    mass_in_service_kg: int | None = None
    tpmlm_kg: int | None = None
    image_references: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "reference": self.reference,
            "vehicle_key": self.vehicle_key,
            "jurisdiction": self.jurisdiction,
            "resident_in": self.resident_in,
            "issued_at": self.issued_at.isoformat() if self.issued_at else None,
            "vin": self.vin,
            "eu_category": self.eu_category,
            "seats": self.seats,
            "mass_in_service_kg": self.mass_in_service_kg,
            "tpmlm_kg": self.tpmlm_kg,
            "image_references": list(self.image_references),
        }


def parse_owner_document(payload: dict) -> OwnerDocument:
    if payload.get("force_pass") or payload.get("override") or payload.get("set_buy_candidate"):
        raise ValueError("Owner text cannot override a gate.")
    kind = str(payload.get("kind") or "").upper()
    if kind not in DOCUMENT_KINDS:
        raise ValueError(f"Unsupported document kind {kind}.")
    reference = str(payload.get("reference") or "").strip()
    if not reference:
        raise ValueError("A document reference is required. A favourable sentence is not evidence.")
    issued = payload.get("issued_at")
    issued_at = datetime.fromisoformat(issued) if issued else None
    if issued_at is not None and issued_at.tzinfo is None:
        raise ValueError("issued_at must include a timezone.")
    images = tuple(str(item) for item in payload.get("image_references") or () if str(item).strip())
    return OwnerDocument(
        kind=kind,
        reference=reference,
        vehicle_key=payload.get("vehicle_key"),
        jurisdiction=(str(payload["jurisdiction"]).upper() if payload.get("jurisdiction") else None),
        resident_in=(str(payload["resident_in"]).upper() if payload.get("resident_in") else None),
        issued_at=issued_at,
        vin=str(payload["vin"]).upper() if payload.get("vin") else None,
        eu_category=str(payload["eu_category"]).upper() if payload.get("eu_category") else None,
        seats=int(payload["seats"]) if payload.get("seats") is not None else None,
        mass_in_service_kg=int(payload["mass_in_service_kg"]) if payload.get("mass_in_service_kg") is not None else None,
        tpmlm_kg=int(payload["tpmlm_kg"]) if payload.get("tpmlm_kg") is not None else None,
        image_references=images,
    )


def apply_owner_document(case: VehicleCase, document: OwnerDocument) -> None:
    """Copy only structured fields the provenance and tax engines already require."""

    if document.kind == "V5C" and document.jurisdiction and document.resident_in:
        case.provenance.v5c_original = KeeperEvidence(
            jurisdiction=document.jurisdiction,
            resident_in=document.resident_in,
            document="V5C",
            issued_at=document.issued_at,
        )
    if document.kind == "NI_IMPORT_DECLARATION" and document.reference and document.vin:
        case.provenance.ni_import_declaration_reference = document.reference
        case.provenance.ni_import_declaration_vin = document.vin
        case.provenance.vehicle_vin = document.vin
        if case.identity.vin is None:
            case.identity.vin = document.vin
    if document.kind == "VIN" and document.vin:
        case.identity.vin = document.vin
        case.provenance.vehicle_vin = document.vin
    if document.kind == "COC" and document.eu_category and document.seats is not None and document.mass_in_service_kg and document.tpmlm_kg:
        case.homologation = Homologation(
            eu_category=document.eu_category,
            seats=document.seats,
            mass_in_service_kg=document.mass_in_service_kg,
            tpmlm_kg=document.tpmlm_kg,
            document="CoC",
            reference=document.reference,
        )
    if document.kind == "WEIGHT_PLATE" and document.mass_in_service_kg and document.tpmlm_kg and case.homologation is not None:
        current = case.homologation
        case.homologation = Homologation(
            eu_category=current.eu_category,
            seats=current.seats,
            mass_in_service_kg=document.mass_in_service_kg,
            tpmlm_kg=document.tpmlm_kg,
            document=current.document,
            reference=document.reference or current.reference,
            separate_passenger_and_cargo_units=current.separate_passenger_and_cargo_units,
        )


def note_owner_documents(case: VehicleCase, ledger: EvidenceLedger) -> None:
    for document in case.owner_documents:
        if not isinstance(document, OwnerDocument):
            continue
        ledger.add(
            EvidenceRecord(
                field=f"owner_document:{document.kind}",
                posture=EvidencePosture.PROVEN,
                status="SUPPLIED",
                confidence=Decimal("0.6"),
                source="owner",
                interpretation=(
                    f"The owner supplied {document.kind} reference {document.reference}. "
                    "Supplying the file does not pass a gate. Only structured fields already "
                    "required by the provenance or tax rules are read."
                ),
                blocking=False,
                raw_reference=document.reference,
            )
        )
