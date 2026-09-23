"""Commercial-vehicle enumerations. Unknown is never a pass."""

from __future__ import annotations

import enum


class EvidencePosture(str, enum.Enum):
    PROVEN = "PROVEN"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


class ProvenanceState(str, enum.Enum):
    ROI_NATIVE = "ROI_NATIVE"
    NI_PRE_2021_PROVEN = "NI_PRE_2021_PROVEN"
    NI_POST_2020_IMPORT_PROVEN = "NI_POST_2020_IMPORT_PROVEN"
    LIKELY_NI_NEEDS_DOCUMENTS = "LIKELY_NI_NEEDS_DOCUMENTS"
    GB_ORIGIN = "GB_ORIGIN"
    GB_TO_NI_UNPROVEN = "GB_TO_NI_UNPROVEN"
    UNKNOWN = "UNKNOWN"


class RegistrationSignal(str, enum.Enum):
    IE_FORMAT = "IE_FORMAT"
    NI_FORMAT_WEAK = "NI_FORMAT_WEAK"
    GB_FORMAT = "GB_FORMAT"
    UNKNOWN = "UNKNOWN"


class VrtState(str, enum.Enum):
    VRT_CONFIRMED = "VRT_CONFIRMED"
    VRT_LIKELY = "VRT_LIKELY"
    VRT_REQUIRES_DATA = "VRT_REQUIRES_DATA"
    VRT_NOT_ELIGIBLE = "VRT_NOT_ELIGIBLE"


class CommercialClass(str, enum.Enum):
    N1_GOODS = "N1_GOODS"
    CREW_OR_MULTI_SEAT = "CREW_OR_MULTI_SEAT"
    PASSENGER = "PASSENGER"
    PARTS_OR_NOT_A_VEHICLE = "PARTS_OR_NOT_A_VEHICLE"
    UNKNOWN = "UNKNOWN"


class CandidateState(str, enum.Enum):
    BUY_CANDIDATE = "BUY_CANDIDATE"
    MANUAL_EVIDENCE_REQUIRED = "MANUAL_EVIDENCE_REQUIRED"
    PRICE_TOO_HIGH = "PRICE_TOO_HIGH"
    REJECT = "REJECT"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class CertificationPosture(str, enum.Enum):
    SHADOW = "SHADOW"
    CERTIFIED = "CERTIFIED"


class LiquidityClass(str, enum.Enum):
    DEEP = "DEEP"
    ADEQUATE = "ADEQUATE"
    THIN = "THIN"
    ILLIQUID = "ILLIQUID"
    UNKNOWN = "UNKNOWN"


class ObservationStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    PRICE_REDUCED = "PRICE_REDUCED"
    PRICE_INCREASED = "PRICE_INCREASED"
    DISAPPEARED = "DISAPPEARED"
    RELISTED = "RELISTED"
    RETURNED = "RETURNED"
    REALISED_SALE = "REALISED_SALE"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class CheckOutcome(str, enum.Enum):
    CLEAR = "CLEAR"
    FAIL = "FAIL"
    ANOMALY = "ANOMALY"
    NOT_CHECKED = "NOT_CHECKED"


class AuctionVatTreatment(str, enum.Enum):
    STANDARD_ON_HAMMER = "STANDARD_ON_HAMMER"
    MARGIN_SCHEME = "MARGIN_SCHEME"
    NO_VAT = "NO_VAT"
    UNKNOWN = "UNKNOWN"


class BodyKind(str, enum.Enum):
    PANEL = "PANEL"
    CHASSIS = "CHASSIS"
    TIPPER = "TIPPER"
    DROPSIDE = "DROPSIDE"
    CREW = "CREW"
    KOMBI = "KOMBI"
    MINIBUS = "MINIBUS"
    WINDOW = "WINDOW"
    LUTON = "LUTON"
    UNKNOWN = "UNKNOWN"


class Fuel(str, enum.Enum):
    DIESEL = "DIESEL"
    PETROL = "PETROL"
    ELECTRIC = "ELECTRIC"
    HYBRID = "HYBRID"
    PHEV = "PHEV"
    UNKNOWN = "UNKNOWN"


class Co2Basis(str, enum.Enum):
    WLTP = "WLTP"
    NEDC = "NEDC"
    UNKNOWN = "UNKNOWN"
