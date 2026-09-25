"""Conservative tax scenarios still produce a reconciled max bid."""

from decimal import Decimal

from app.domains.vehicles.owner_view import owner_quote, plain_provenance
from app.domains.vehicles.tax_scenarios import build_scenarios, candidate_taric, default_t426_schedule, jurisdiction_from


def test_ugz_is_likely_ni_unproven() -> None:
    jurisdiction, status = jurisdiction_from("UGZ 3040", "LIKELY_NI_NEEDS_DOCUMENTS")
    assert jurisdiction == "LIKELY_NI"
    assert status == "UNPROVEN"


def test_gb_plate_is_likely_gb() -> None:
    jurisdiction, status = jurisdiction_from("AF22 URG", "GB_ORIGIN")
    assert jurisdiction == "LIKELY_GB"
    assert status == "UNPROVEN"


def test_taric_candidate_for_used_diesel_van() -> None:
    row = candidate_taric(fuel="diesel", gvw_tonnes=Decimal("3.5"), engine_cc=1500)
    assert row["candidate_taric_code"] == "87042199"
    assert row["third_country_duty_rate"] == "0.10"


def test_gb_scenario_fills_safe_max_bid() -> None:
    quote = owner_quote(
        {
            "prebid_group": "ECONOMICALLY_INTERESTING_TAX_DILIGENCE",
            "provenance_status": "GB_ORIGIN",
            "title": "2022 vauxhall combo 1.5 PANEL DIESEL",
            "vehicle": "2022 vauxhall combo 1.5 PANEL DIESEL",
            "valuation": {"expected_achievable_eur": "11518.56", "conservative_eur": "11518.56", "quick_sale_eur": "10597"},
            "economics": {"pre_tax_hammer_ceiling_eur": "5490"},
        },
        fx="1.1634671321",
        registration="AF22 URG",
        schedule=default_t426_schedule(Decimal("1.1634671321")),
    )
    assert quote["max_bid_known"] is True
    assert quote["max_bid_gbp"]
    assert Decimal(quote["customs_eur"]) > 0
    assert Decimal(quote["import_vat_eur"]) > 0
    assert Decimal(quote["vrt_eur"]) > Decimal("200")
    assert quote["alt_label"] == "IF UK ORIGIN PROVEN"
    assert Decimal(quote["profit_eur"]) == Decimal(quote["sell_eur"]) - Decimal(quote["all_in_eur"])


def test_ni_scenario_shows_both_max_bids() -> None:
    quote = owner_quote(
        {
            "prebid_group": "ECONOMICALLY_INTERESTING_TAX_DILIGENCE",
            "provenance_status": "LIKELY_NI_NEEDS_DOCUMENTS",
            "title": "2021 vauxhall combo 1.5 PANEL DIESEL",
            "vehicle": "2021 vauxhall combo 1.5 PANEL DIESEL",
            "valuation": {"expected_achievable_eur": "9323.53", "conservative_eur": "9323.53", "quick_sale_eur": "8500"},
            "economics": {"pre_tax_hammer_ceiling_eur": "4026"},
        },
        fx="1.1634671321",
        registration="UGZ 3040",
        schedule=default_t426_schedule(Decimal("1.1634671321")),
    )
    assert quote["tax_label"] == "LIKELY NORTHERN IRELAND"
    assert quote["max_bid_gbp"]
    assert quote["alt_max_bid_gbp"]
    assert Decimal(quote["alt_max_bid_gbp"]) > Decimal(quote["max_bid_gbp"])
    assert "NI import declaration" in " ".join(quote["documents"])


def test_plain_provenance_ni_plate_text() -> None:
    assert plain_provenance("LIKELY_NI_NEEDS_DOCUMENTS") == "LIKELY NORTHERN IRELAND"


def test_build_scenarios_withholds_without_sell() -> None:
    result = build_scenarios({"prebid_group": "MARKET_INSUFFICIENT", "provenance_status": "GB_ORIGIN"}, registration="AF22 URG", fx="1.16")
    assert result["safe_max_bid_gbp"] is None
