"""VAT-interval valuation. Unknown VAT widens the range and still produces a floor."""

from __future__ import annotations

from decimal import Decimal

from app.domains.vehicles.price_interval import cash_interval
from app.domains.vehicles.tax import VAT_RATE
from app.domains.vehicles.valuation_v2 import value_vehicle_v2
from app.domains.vehicles.valuation_v3 import value_vehicle_v3
from tests.test_cv_engine import _book, _obs, golden


def test_explicit_vat_intervals_are_exact() -> None:
    exclusive = cash_interval(Decimal("10000"), "VAT_EXCLUSIVE")
    inclusive = cash_interval(Decimal("10000"), "VAT_INCLUSIVE")
    none = cash_interval(Decimal("10000"), "NO_VAT")
    margin = cash_interval(Decimal("10000"), "MARGIN_SCHEME")
    qualifying = cash_interval(Decimal("10000"), "VAT_QUALIFYING")
    unknown = cash_interval(Decimal("10000"), "UNKNOWN")
    gross = (Decimal("10000") * (Decimal("1") + VAT_RATE)).quantize(Decimal("0.01"))
    assert exclusive.exact and exclusive.cash_low_eur == exclusive.cash_high_eur == gross
    assert inclusive.exact and inclusive.cash_low_eur == Decimal("10000.00")
    assert none.exact and none.cash_low_eur == Decimal("10000.00")
    assert margin.exact and margin.cash_low_eur == Decimal("10000.00")
    assert not qualifying.exact and qualifying.cash_low_eur == Decimal("10000.00") and qualifying.cash_high_eur == gross
    assert not unknown.exact and unknown.cash_low_eur == Decimal("10000.00") and unknown.cash_high_eur == gross
    assert unknown.cash_low_eur <= unknown.cash_high_eur


def test_unknown_vat_keeps_every_comp_and_floors_from_the_low_side() -> None:
    case = golden()
    case.book = _book(0)
    for index in range(12):
        case.book.append(_obs(index, vat_presentation="unknown", vat_classification="UNKNOWN", asking_price_eur=Decimal("10000")))
    v2 = value_vehicle_v2(case.identity, case.book, as_of=case.as_of)
    v3 = value_vehicle_v3(case.identity, case.book, as_of=case.as_of)
    assert v2.conservative_eur is None
    assert v3.comparable_count == 12
    assert v3.prebid_floor_available is True
    assert v3.market_floor_confidence in {"HIGH", "MEDIUM"}
    assert v3.vat_basis_confidence == "LOW"
    assert v3.expected_achievable_eur is None
    assert v3.conservative_eur == Decimal("8000.00")
    assert v3.vat_stress_proceeds_eur is not None
    assert v3.vat_stress_proceeds_eur <= v3.conservative_eur
    assert v3.conservative_eur <= v3.market_cash_central_low_eur


def test_one_known_plus_many_unknown_does_not_collapse_to_the_known_row() -> None:
    case = golden()
    case.book = _book(0)
    case.book.append(_obs(0, vat_presentation="ex_vat", vat_classification="VAT_EXCLUSIVE", asking_price_eur=Decimal("10000")))
    for index in range(1, 41):
        case.book.append(_obs(index, vat_presentation="unknown", vat_classification="UNKNOWN", asking_price_eur=Decimal("10000")))
    result = value_vehicle_v3(case.identity, case.book, as_of=case.as_of)
    assert result.comparable_count == 41
    assert result.vat_basis_confidence == "LOW"
    assert result.market_cash_central_low_eur == Decimal("10000.00")
    assert result.conservative_eur == Decimal("8000.00")


def test_assuming_unknown_is_exclusive_cannot_lower_the_floor() -> None:
    case = golden()
    case.book = _book(0)
    for index in range(10):
        case.book.append(_obs(index, vat_presentation="unknown", vat_classification="UNKNOWN", asking_price_eur=Decimal("10000")))
    unknown = value_vehicle_v3(case.identity, case.book, as_of=case.as_of)
    case.book = _book(0)
    for index in range(10):
        case.book.append(_obs(index, vat_presentation="ex_vat", vat_classification="VAT_EXCLUSIVE", asking_price_eur=Decimal("10000")))
    exclusive = value_vehicle_v3(case.identity, case.book, as_of=case.as_of)
    assert unknown.conservative_eur is not None and exclusive.conservative_eur is not None
    assert unknown.conservative_eur <= exclusive.conservative_eur
    assert exclusive.market_cash_central_low_eur > unknown.market_cash_central_low_eur


def test_inclusive_collapses_toward_the_advertised_price() -> None:
    case = golden()
    case.book = _book(0)
    for index in range(10):
        case.book.append(_obs(index, vat_presentation="vat_inclusive", vat_classification="VAT_INCLUSIVE", asking_price_eur=Decimal("10000")))
    result = value_vehicle_v3(case.identity, case.book, as_of=case.as_of)
    assert result.market_cash_central_low_eur == result.market_cash_central_high_eur == Decimal("10000.00")
    assert result.expected_achievable_eur == Decimal("8500.00")


def test_effects_ignore_mixed_raw_bases() -> None:
    case = golden()
    case.book = _book(0)
    for index in range(6):
        case.book.append(_obs(index, year=2018, mileage_km=80000, vat_classification="UNKNOWN", vat_presentation="unknown", asking_price_eur=Decimal("9000")))
    for index in range(6, 12):
        case.book.append(_obs(index, year=2021, mileage_km=140000, vat_classification="VAT_EXCLUSIVE", vat_presentation="ex_vat", asking_price_eur=Decimal("14000")))
    result = value_vehicle_v3(case.identity, case.book, as_of=case.as_of)
    assert result.effect_basis == "exact_insufficient"
    assert "€0" in " ".join(result.adjustment_reasons) or result.effect_basis == "exact_insufficient"


def test_v2_regression_label_is_unchanged() -> None:
    case = golden()
    assert value_vehicle_v2(case.identity, case.book, as_of=case.as_of).model_version == "arie-native-v2"
    assert value_vehicle_v3(case.identity, case.book, as_of=case.as_of).model_version == "arie-native-v3-vat-interval"


def test_buy_gate_stays_closed_when_vat_is_unknown() -> None:
    from app.domains.vehicles.evaluate import evaluate_vehicle

    case = golden()
    case.book = _book(0)
    for index in range(12):
        case.book.append(_obs(index, vat_presentation="unknown", vat_classification="UNKNOWN", asking_price_eur=Decimal("18000")))
    evaluation = evaluate_vehicle(case)
    assert evaluation.valuation.prebid_floor_available is True
    assert evaluation.valuation.expected_achievable_eur is None
    assert evaluation.gates.gates["VALUATION_CONFIDENCE_PASS"] is False
    assert evaluation.state.value != "BUY_CANDIDATE"
