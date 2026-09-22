"""Owner surface for ARIE-CV. It stays off the camera health path."""

from __future__ import annotations

import json
from datetime import timedelta

from fastapi.testclient import TestClient

from app.domains.vehicles.board import clear
from app.main import create_app
from tests.test_cv_engine import AS_OF, VIN, golden


def _payload_from_case() -> dict:
    case = golden()
    return {
        "title": case.listing.title,
        "as_of": case.as_of.isoformat(),
        "source_id": case.listing.source_id,
        "external_id": case.listing.external_id,
        "currency": "EUR",
        "current_bid": "7000",
        "identity": {
            "manufacturer": "ford",
            "model_family": "transit_custom",
            "body": "PANEL",
            "fuel": "DIESEL",
            "transmission": "manual",
            "wheelbase": "l1",
            "roof": "h1",
            "derivative": "300",
            "year": 2019,
            "vin": VIN,
            "mileage_km": 100000,
        },
        "provenance": {
            "irish_registration_certificate": True,
            "irish_registration_reference": "VRC-1",
            "vehicle_vin": VIN,
            "auction_country": "IE",
        },
        "history": {
            "listing_mileage_km": 100000,
            "readings": [
                {"observed_at": "2024-06-01T00:00:00+00:00", "mileage_km": 80000, "source": "nct", "reference": "nct-1"},
                {"observed_at": "2025-06-01T00:00:00+00:00", "mileage_km": 95000, "source": "nct", "reference": "nct-2"},
            ],
            "stolen": {"outcome": "CLEAR", "posture": "PROVEN", "source": "history-fixture", "interpretation": "clear", "blocking": False},
            "finance": {"outcome": "CLEAR", "posture": "PROVEN", "source": "history-fixture", "interpretation": "clear", "blocking": False},
            "write_off": {"outcome": "CLEAR", "posture": "PROVEN", "source": "history-fixture", "interpretation": "clear", "blocking": False},
            "keys": 2,
        },
        "homologation": {
            "eu_category": "N1",
            "seats": 3,
            "mass_in_service_kg": 1900,
            "tpmlm_kg": 2800,
            "document": "CoC",
            "reference": "COC-1",
        },
        "fee_schedule": {
            "schedule_id": "fixture-commercial",
            "source_id": "fixture",
            "version": "v1",
            "effective_from": AS_OF.isoformat(),
            "retrieved_at": AS_OF.isoformat(),
            "evidence_url": "fixture://fees",
            "applies_to": "commercial_vehicles",
            "bands": [{"up_to_eur": None, "percent": "0.10"}],
            "minimum_premium_eur": "10",
            "premium_vat_rate": "0.23",
        },
        "vat_treatment": "NO_VAT",
        "hammer_includes_vat": False,
        "transport_eur": "250",
        "transport_posture": "PROVEN",
        "payment_fee_eur": "0",
        "payment_fee_posture": "PROVEN",
        "mechanical_inspected": True,
        "market_observations": [
            {
                "observation_id": f"http-{index}",
                "listing_id": f"http-listing-{index}",
                "observed_at": (AS_OF - timedelta(hours=20)).isoformat(),
                "manufacturer": "ford",
                "model_family": "transit_custom",
                "year": 2019,
                "fuel": "DIESEL",
                "body": "PANEL",
                "wheelbase": "l1",
                "roof": "h1",
                "transmission": "manual",
                "derivative": "300",
                "mileage_km": 100000,
                "asking_price_eur": "18000",
                "seller_type": "dealer",
                "vat_presentation": "ex_vat",
                "location": "Dublin",
                "status": "ACTIVE",
                "source": "owner_capture",
            }
            for index in range(12)
        ],
    }


def test_cv_dashboard_defaults_to_an_empty_candidate_list() -> None:
    clear()
    with TestClient(create_app()) as client:
        page = client.get("/cv")
        sources = client.get("/cv/sources")
    assert page.status_code == 200
    assert "No vehicles in this view" in page.text
    assert "does not bid" in page.text
    assert sources.json()["purchasing_enabled"] is False
    assert sources.json()["live_fetchers"] == []


def test_incomplete_case_is_not_buy_candidate() -> None:
    clear()
    with TestClient(create_app()) as client:
        response = client.post(
            "/cv/api/evaluate",
            json={"title": "Citroen Berlingo", "as_of": "2026-09-22T12:00:00+00:00"},
        )
    body = response.json()
    assert response.status_code == 200
    assert body["state"] != "BUY_CANDIDATE"
    assert body["purchasing_recommendation"] is False
    assert body["tax"]["vrt_eur"] is None


def test_evidenced_case_appears_as_a_shadow_candidate() -> None:
    clear()
    with TestClient(create_app()) as client:
        response = client.post("/cv/api/evaluate", json=_payload_from_case())
        page = client.get("/cv")
    body = response.json()
    assert body["state"] == "BUY_CANDIDATE"
    assert body["purchasing_recommendation"] is False
    assert "Transit" in page.text or "transit" in page.text
    assert "BUY_CANDIDATE" in page.text
    assert "SHADOW" in page.text
    json.dumps(body)
