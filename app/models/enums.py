"""Shared enumerations. Values are persisted as strings."""

from __future__ import annotations

import enum


class SourceStatus(str, enum.Enum):
    LIVE = "LIVE"
    DEGRADED = "DEGRADED"
    BLOCKED_CREDENTIALS = "BLOCKED_CREDENTIALS"
    BLOCKED_POLICY = "BLOCKED_POLICY"
    BLOCKED_TECHNICAL = "BLOCKED_TECHNICAL"
    DISABLED = "DISABLED"


class SourceKind(str, enum.Enum):
    ACQUISITION = "acquisition"
    COMPARABLE = "comparable"
    REFERENCE = "reference"
    FX = "fx"
    MANUAL = "manual"


class EvidenceType(str, enum.Enum):
    REALISED_SALE = "realised_sale"
    CURRENT_ASKING = "current_asking"
    DEALER_RETAIL = "dealer_retail"
    TRADE_IN = "trade_in"
    AUCTION_HAMMER = "auction_hammer"
    ESTIMATE = "estimate"
    OWNER_RECORDED = "owner_recorded"


class ConditionGrade(str, enum.Enum):
    NEW = "new"
    OPEN_BOX = "open_box"
    EXCELLENT = "excellent"
    VERY_GOOD = "very_good"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    FOR_PARTS = "for_parts"
    UNKNOWN = "unknown"


class Decision(str, enum.Enum):
    BUY = "BUY"
    WATCH = "WATCH"
    IGNORE = "IGNORE"
    REVIEW = "REVIEW"


class IdentityLevel(str, enum.Enum):
    EXACT = "exact"
    VARIANT = "variant"
    FAMILY = "family"
    CATEGORY = "category"
    UNKNOWN = "unknown"


class ScanStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class InventoryState(str, enum.Enum):
    WATCHING = "watching"
    PURCHASED = "purchased"
    RECEIVED = "received"
    REFURBISHED = "refurbished"
    LISTED = "listed"
    SOLD = "sold"
    RETURNED = "returned"
    WRITTEN_OFF = "written_off"


class AssumptionClass(str, enum.Enum):
    MEASURED = "measured"
    CONFIGURED = "configured"
    ASSUMPTION = "assumption"
    ACCOUNTANT_REQUIRED = "accountant_required"


class Corridor(str, enum.Enum):
    IE_DOMESTIC = "ie_domestic"
    NI_TO_IE = "ni_to_ie"
    GB_TO_IE = "gb_to_ie"
    EU_TO_IE = "eu_to_ie"
    ROW_TO_IE = "row_to_ie"


LIVE = SourceStatus.LIVE
DEGRADED = SourceStatus.DEGRADED
BLOCKED_CREDENTIALS = SourceStatus.BLOCKED_CREDENTIALS
BLOCKED_POLICY = SourceStatus.BLOCKED_POLICY
BLOCKED_TECHNICAL = SourceStatus.BLOCKED_TECHNICAL
DISABLED = SourceStatus.DISABLED
ACQUISITION = SourceKind.ACQUISITION
COMPARABLE = SourceKind.COMPARABLE
FX = SourceKind.FX
MANUAL = SourceKind.MANUAL
DEALER_RETAIL = EvidenceType.DEALER_RETAIL
CURRENT_ASKING = EvidenceType.CURRENT_ASKING
REALISED_SALE = EvidenceType.REALISED_SALE
