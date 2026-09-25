"""Money accuracy: all-in profit, auction fees once, conservative VRT/TARIC."""

from decimal import Decimal

from app.core.money import money
from app.domains.vehicles.enums import AuctionVatTreatment
from app.domains.vehicles.owner_view import owner_quote
from app.domains.vehicles.tax_scenarios import (
    all_in_at_hammer,
    build_scenarios,
    candidate_taric,
    default_t426_schedule,
    solve_owner_max_hammer,
    spec_from_evaluation,
    vrt_scenarios,
)


def _eval(sell: str = "11518.56", quick: str = "10597", title: str = "2022 vauxhall combo 1.5 PANEL DIESEL", provenance: str = "GB_ORIGIN") -> dict:
    return {
        "prebid_group": "ECONOMICALLY_INTERESTING_TAX_DILIGENCE",
        "provenance_status": provenance,
        "title": title,
        "vehicle": title,
        "valuation": {"conservative_eur": sell, "expected_achievable_eur": sell, "quick_sale_eur": quick},
    }


def test_profit_equals_sell_minus_all_in() -> None:
    fx = Decimal("1.1634671321")
    schedule = default_t426_schedule(fx)
    result = solve_owner_max_hammer(
        sell_eur=Decimal("11518.56"),
        quick_sale_eur=Decimal("10597"),
        schedule=schedule,
        vat_treatment=AuctionVatTreatment.STANDARD_ON_HAMMER,
        hammer_includes_vat=False,
        lot_vat_rate=Decimal("0.20"),
        duty_rate=Decimal("0.10"),
        vrt_eur=Decimal("1532"),
    )
    assert result is not None
    assert result.profit_eur == money(result.sell_eur - result.all_in_eur)


def test_each_cost_line_appears_once() -> None:
    schedule = default_t426_schedule(Decimal("1.16"))
    result = all_in_at_hammer(
        hammer_eur=Decimal("3000"),
        sell_eur=Decimal("11518.56"),
        schedule=schedule,
        vat_treatment=AuctionVatTreatment.STANDARD_ON_HAMMER,
        hammer_includes_vat=False,
        lot_vat_rate=Decimal("0.20"),
        duty_rate=Decimal("0.10"),
        vrt_eur=Decimal("1532"),
    )
    for key in ("hammer", "buyer_premium", "premium_vat", "auction_lot_vat", "payment_fee", "customs_duty", "import_vat", "vrt", "transport", "insurance", "reconditioning", "selling_cost"):
        assert key in result.lines
    assert list(result.lines).count("buyer_premium") == 1
    assert list(result.lines).count("reconditioning") == 1
    assert list(result.lines).count("selling_cost") == 1
    assert list(result.lines).count("transport") == 1


def test_euro200_not_safe_default_without_homologation() -> None:
    vrt = vrt_scenarios(sell_eur=Decimal("11518.56"), spec=spec_from_evaluation(_eval()))
    assert vrt["euro200_supported"] is False
    assert Decimal(str(vrt["safe_vrt_eur"])) > Decimal("200")


def test_taric_uses_engine_and_fuel() -> None:
    diesel = candidate_taric(fuel="diesel", gvw_tonnes=Decimal("3.5"), engine_cc=1500)
    assert diesel["candidate_taric_code"] == "87042199"
    assert diesel["third_country_duty_rate"] == "0.10"
    big = candidate_taric(fuel="diesel", gvw_tonnes=Decimal("3.5"), engine_cc=3000)
    assert big["candidate_taric_code"] == "87042139"
    assert big["third_country_duty_rate"] == "0.22"
    electric = candidate_taric(fuel="electric", gvw_tonnes=Decimal("3.5"))
    assert "8704" in electric["candidate_taric_code"]
    assert electric["candidate_taric_code"] != "87042199"


def test_unknown_engine_does_not_use_low_band() -> None:
    row = candidate_taric(fuel="diesel", gvw_tonnes=Decimal("3.5"), engine_cc=None)
    assert row["third_country_duty_rate"] == "0.22"


def test_ni_proof_zeroes_only_customs_and_import_vat() -> None:
    schedule = default_t426_schedule(Decimal("1.16"))
    gb = all_in_at_hammer(
        hammer_eur=Decimal("4000"),
        sell_eur=Decimal("16236"),
        schedule=schedule,
        vat_treatment=AuctionVatTreatment.STANDARD_ON_HAMMER,
        hammer_includes_vat=False,
        lot_vat_rate=Decimal("0.20"),
        duty_rate=Decimal("0.10"),
        vrt_eur=Decimal("2000"),
        ni_clear=False,
    )
    ni = all_in_at_hammer(
        hammer_eur=Decimal("4000"),
        sell_eur=Decimal("16236"),
        schedule=schedule,
        vat_treatment=AuctionVatTreatment.STANDARD_ON_HAMMER,
        hammer_includes_vat=False,
        lot_vat_rate=Decimal("0.20"),
        duty_rate=Decimal("0.10"),
        vrt_eur=Decimal("2000"),
        ni_clear=True,
    )
    assert gb.lines["customs_duty"] > 0
    assert gb.lines["import_vat"] > 0
    assert ni.lines["customs_duty"] == 0
    assert ni.lines["import_vat"] == 0
    assert ni.lines["vrt"] == Decimal("2000.00")


def test_solved_hammer_meets_hurdles_and_one_euro_more_fails() -> None:
    schedule = default_t426_schedule(Decimal("1.1634671321"))
    result = solve_owner_max_hammer(
        sell_eur=Decimal("11518.56"),
        quick_sale_eur=Decimal("10597"),
        schedule=schedule,
        vat_treatment=AuctionVatTreatment.STANDARD_ON_HAMMER,
        hammer_includes_vat=False,
        lot_vat_rate=Decimal("0.20"),
        duty_rate=Decimal("0.10"),
        vrt_eur=Decimal("1532"),
    )
    assert result is not None
    assert result.profit_eur >= Decimal("800")
    assert result.roi is not None and result.roi >= Decimal("0.15")
    higher = all_in_at_hammer(
        hammer_eur=money(result.hammer_eur + Decimal("1")),
        sell_eur=Decimal("11518.56"),
        schedule=schedule,
        vat_treatment=AuctionVatTreatment.STANDARD_ON_HAMMER,
        hammer_includes_vat=False,
        lot_vat_rate=Decimal("0.20"),
        duty_rate=Decimal("0.10"),
        vrt_eur=Decimal("1532"),
    )
    assert higher.profit_eur < result.profit_eur
    from app.domains.vehicles.tax_scenarios import _feasible

    # One euro above must fail at least one hurdle within solver precision.
    assert not _feasible(higher, quick_sale_eur=Decimal("10597"), required_profit=Decimal("800"), required_roi=Decimal("0.15"))


def test_lot8_style_quote_reconciles() -> None:
    quote = owner_quote(_eval(), fx="1.1634671321", registration="AF22 URG", schedule=default_t426_schedule(Decimal("1.1634671321")))
    assert quote["max_bid_known"] is True
    assert Decimal(quote["profit_eur"]) == money(Decimal(quote["sell_eur"]) - Decimal(quote["all_in_eur"]))
    assert Decimal(quote["vrt_eur"]) > Decimal("200")
    # GVW not invented → conservative 22% leaf until TPMLM is evidenced.
    assert quote["taric"]["third_country_duty_rate"] == "0.22"
    assert quote["bid_label"] == "SAFE GB IMPORT"


def test_build_scenarios_passes_vehicle_into_taric() -> None:
    result = build_scenarios(_eval(title="2021 ford transit 2.0 EcoBlue PANEL DIESEL"), registration="FY21 ZWL", fx="1.1634671321")
    assert result["spec"]["engine_cc"] == 2000
    assert result["taric"]["inputs"]["engine_cc"] == 2000
    assert result["taric"]["third_country_duty_rate"] == "0.22"


def test_evidenced_gvw_and_small_engine_uses_10_percent() -> None:
    evaluation = _eval(title="2022 vauxhall combo 1.5 PANEL DIESEL")
    evaluation["homologation"] = {"tpmlm_kg": 2500}
    result = build_scenarios(evaluation, registration="AF22 URG", fx="1.1634671321")
    assert result["spec"]["engine_cc"] == 1500
    assert result["taric"]["candidate_taric_code"] == "87042199"
    assert result["taric"]["third_country_duty_rate"] == "0.10"


def test_ni_unproven_label() -> None:
    quote = owner_quote(
        _eval(title="2019 volkswagen crafter 2.0 TDI PANEL DIESEL", provenance="LIKELY_NI_NEEDS_DOCUMENTS"),
        fx="1.1634671321",
        registration="WHZ 9432",
        schedule=default_t426_schedule(Decimal("1.1634671321")),
    )
    assert quote["bid_label"] == "SAFE WITHOUT NI PROOF"
    assert quote["alt_label"] == "IF NI STATUS PROVEN"
    assert quote["alt_vrt_label"] == "IF NI + €200 VRT PROVEN"
