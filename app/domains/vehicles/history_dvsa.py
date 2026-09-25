"""DVSA MOT History API contract.

Official documentation:
https://documentation.history.mot.api.gov.uk/

No request is sent unless the owner has registered a key. Absence stays
NOT_CHECKED. A mileage reading is not, by itself, proof of NI customs status.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

DVSA_REGISTER_URL = "https://documentation.history.mot.api.gov.uk/mot-history-api/register"
DVSA_AUTH_URL = "https://documentation.history.mot.api.gov.uk/mot-history-api/authentication/"
DVSA_API_ROOT = "https://history.mot.api.gov.uk"
DVSA_REGISTRATION_PATH = "/v1/trade/vehicles/registration/{registration}"
DVSA_VIN_PATH = "/v1/trade/vehicles/vin/{vin}"
DVSA_SCOPE = "https://tapi.dvsa.gov.uk/.default"

REQUIRED_ENV = (
    "DVSA_CLIENT_ID",
    "DVSA_CLIENT_SECRET",
    "DVSA_API_KEY",
    "DVSA_TOKEN_URL",
    "DVSA_SCOPE",
)


@dataclass(frozen=True, slots=True)
class MotTestRecord:
    completed_at: datetime | None
    result: str
    odometer_value: int | None
    odometer_unit: str
    jurisdiction: str | None
    raw_reference: str


def dvsa_status() -> dict[str, object]:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name, "").strip()]
    return {
        "provider": "DVSA MOT History API",
        "api": DVSA_API_ROOT,
        "status": "BLOCKED_CREDENTIALS" if missing else "CONFIGURED",
        "missing_env": missing,
        "cost": "Registration is free. DVSA reviews the application; approval can take several working days.",
        "scope": os.environ.get("DVSA_SCOPE", "").strip() or DVSA_SCOPE,
        "registration_steps": [
            f"Register at {DVSA_REGISTER_URL} as a business or individual.",
            "Wait for DVSA to email a client ID, client secret, API key, scope URL, and token URL.",
            "Set DVSA_CLIENT_ID, DVSA_CLIENT_SECRET, DVSA_API_KEY, DVSA_TOKEN_URL, and DVSA_SCOPE.",
            "Scope for the new API is https://tapi.dvsa.gov.uk/.default unless DVSA sends a different scope.",
            "Each call sends Authorization: Bearer <token> and X-API-Key.",
            "Token endpoint is the tenant URL DVSA emails, using grant_type=client_credentials.",
            "Do not use the key for 90 days without a call or DVSA will revoke it. Client secrets expire about every two years.",
        ],
        "returns": [
            "Vehicle identity fields DVSA holds, including make, model, fuel, colour, and first used date where present.",
            "MOT tests for GB vehicles since 2005 and Northern Ireland vehicles since 2017, including result, completed date, and odometer.",
            "Defects and advisories on each test where DVSA returns them.",
            "A jurisdiction only when the payload itself names Northern Ireland or Great Britain. Mileage alone is not NI provenance.",
        ],
        "docs": DVSA_AUTH_URL,
    }


def parse_mot_payload(payload: dict[str, Any]) -> tuple[MotTestRecord, ...]:
    tests = payload.get("motTests") or payload.get("mot_tests") or []
    parsed: list[MotTestRecord] = []
    for index, test in enumerate(tests):
        if not isinstance(test, dict):
            continue
        unit = str(test.get("odometerUnit") or test.get("odometer_unit") or "").lower()
        raw_value = test.get("odometerValue")
        if raw_value is None:
            raw_value = test.get("odometer_value")
        value = int(raw_value) if raw_value not in (None, "") else None
        jurisdiction = _jurisdiction(test)
        completed = _completed(test.get("completedDate") or test.get("completed_date"))
        parsed.append(
            MotTestRecord(
                completed_at=completed,
                result=str(test.get("testResult") or test.get("test_result") or ""),
                odometer_value=value,
                odometer_unit=unit,
                jurisdiction=jurisdiction,
                raw_reference=f"mot:{index}",
            )
        )
    return tuple(parsed)


def _jurisdiction(test: dict[str, Any]) -> str | None:
    blob = " ".join(
        str(test.get(key) or "")
        for key in ("location", "testLocation", "country", "region", "source")
    ).upper()
    if "NORTHERN IRELAND" in blob or blob.strip() in {"NI", "NIR"}:
        return "NI"
    if "GREAT BRITAIN" in blob or blob.strip() in {"GB", "UK"}:
        return "GB"
    return None


def _completed(value: object) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed
