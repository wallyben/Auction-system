"""Native valuation v2 keeps v1 and refuses an unanchored price."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.domains.vehicles.effects import EffectModel
from app.domains.vehicles.platforms import platform_for
from app.domains.vehicles.scenarios import vat_decision
from app.domains.vehicles.valuation import value_vehicle
from app.domains.vehicles.valuation_v2 import apply_adjustment as adjust_price
from app.domains.vehicles.valuation_v2 import value_vehicle_v2
from app.sources.registry import all_adapters
from tests.test_cv_engine import AS_OF, _book, _identity, _obs, golden


def test_v1_is_retained_and_v2_is_labelled() -> None:
    case = golden()
    assert value_vehicle(case.identity, case.book, as_of=case.as_of).model_version == "arie-native-v1"
    v2 = value_vehicle_v2(case.identity, case.book, as_of=case.as_of)
    assert v2.model_version == "arie-native-v2"
    assert v2.market_asking_eur == Decimal("18000.00")
    assert v2.confidence_label == "HIGH"
    assert "UNCALIBRATED_ASSUMPTION" in " ".join(v2.notes)
    assert "not a verified realised-sale price" in " ".join(v2.notes)


def test_exact_anchor_dominates_a_looser_comp() -> None:
    case = golden()
    case.book = _book(0)
    case.book.append(_obs(1, asking_price_eur=Decimal("10000")))
    case.book.append(_obs(2, asking_price_eur=Decimal("10000")))
    case.book.append(_obs(3, asking_price_eur=Decimal("10000")))
    case.book.append(_obs(4, asking_price_eur=Decimal("10000")))
    case.book.append(_obs(5, asking_price_eur=Decimal("10000")))
    loose = _obs(6, year=2014, mileage_km=170000, asking_price_eur=Decimal("20000"))
    case.book.append(loose)
    result = value_vehicle_v2(case.identity, case.book, as_of=case.as_of)
    assert result.market_asking_eur == Decimal("10000.00")
    tiers = {row["tier"] for row in result.evidence if row["tier"] in {"A", "B"}}
    assert "A" in tiers
    assert "B" in tiers


def test_moderate_mileage_is_adjusted_and_extreme_mileage_is_rejected() -> None:
    case = golden()
    case.book = _book(0)
    case.book.append(_obs(1, mileage_km=160000, asking_price_eur=Decimal("15000")))
    case.book.append(_obs(2, mileage_km=400000, asking_price_eur=Decimal("4000")))
    result = value_vehicle_v2(case.identity, case.book, as_of=case.as_of)
    reasons = " ".join(reason for row in result.rejected for reason in row.reasons)
    assert "Mileage too far" in reasons
    assert any(row["tier"] == "B" and row["mileage_km"] == 160000 for row in result.evidence)
    assert result.confidence_label == "INSUFFICIENT"


def test_year_adjustment_moves_the_anchor_and_generation_blocks_it() -> None:
    subject = _identity(year=2020)
    comp = _obs(1, year=2019)
    effect = EffectModel(Decimal("650"), Decimal("0"), "family", 12, Decimal("0.5"))
    adjustment = adjust_price(subject, comp, effect, Decimal("10000"))
    assert adjustment == Decimal("650.00")
    case = golden()
    case.identity.generation = "second"
    case.book = _book(0)
    case.book.append(_obs(1, generation="first", asking_price_eur=Decimal("9000")))
    case.book.append(_obs(2, asking_price_eur=Decimal("18000")))
    result = value_vehicle_v2(case.identity, case.book, as_of=case.as_of)
    reasons = " ".join(reason for row in result.rejected for reason in row.reasons)
    assert "Generation mismatch" in reasons
    assert result.market_asking_eur is None or result.market_asking_eur == Decimal("18000.00")


def test_unknown_wheelbase_loses_weight_and_a_mismatch_is_rejected() -> None:
    matched = _obs(1, wheelbase="l1")
    unknown = _obs(2, wheelbase=None)
    mismatch = _obs(3, wheelbase="l2")
    case = golden()
    case.book = _book(0)
    case.book.append(matched)
    case.book.append(unknown)
    case.book.append(mismatch)
    result = value_vehicle_v2(case.identity, case.book, as_of=case.as_of)
    weights = {row["wheelbase"]: Decimal(str(row["similarity_weight"])) for row in result.evidence if row["tier"] in {"A", "B"}}
    assert weights["l1"] > weights["UNKNOWN"]
    reasons = " ".join(reason for row in result.rejected for reason in row.reasons)
    assert "Wheelbase mismatch" in reasons


def test_sibling_and_global_evidence_cannot_anchor_a_price() -> None:
    assert platform_for("berlingo") is not None
    assert platform_for("berlingo").usable_as_direct_comp is False
    sibling_only = golden()
    sibling_only.identity = _identity(manufacturer="citroen", model_family="berlingo", derivative=None)
    sibling_only.book = _book(0)
    for index in range(6):
        sibling_only.book.append(_obs(index, manufacturer="peugeot", model_family="partner", asking_price_eur=Decimal("11000")))
    sibling = value_vehicle_v2(sibling_only.identity, sibling_only.book, as_of=sibling_only.as_of)
    assert sibling.market_asking_eur is None
    assert sibling.confidence_label == "INSUFFICIENT"
    assert sibling.tier_c_count == 6
    assert all(row["tier"] != "A" for row in sibling.evidence)

    obscure = golden()
    obscure.identity = _identity(model_family="obscure_van", manufacturer="none")
    obscure.book = _book(8)
    unanchored = value_vehicle_v2(obscure.identity, obscure.book, as_of=obscure.as_of)
    assert unanchored.market_asking_eur is None
    assert unanchored.confidence_label == "INSUFFICIENT"
    assert unanchored.tier_c_count == 0


def test_unknown_vat_withholds_the_achievable_figure_and_decision_rules() -> None:
    case = golden()
    case.book = _book(0)
    for index in range(8):
        case.book.append(_obs(index, vat_presentation="unknown", asking_price_eur=Decimal("10000")))
    result = value_vehicle_v2(case.identity, case.book, as_of=case.as_of)
    assert result.expected_achievable_eur is None
    assert result.asking_low_eur is not None
    assert result.asking_high_eur is not None
    assert result.asking_high_eur > result.asking_low_eur
    both_good = vat_decision(
        all_in_eur=Decimal("4000"),
        pessimistic_resale_eur=Decimal("8000"),
        optimistic_resale_eur=Decimal("9500"),
    )
    assert both_good["label"] == "ECONOMICALLY_INTERESTING_PENDING_DILIGENCE"
    assert both_good["buy_candidate"] is False
    sensitive = vat_decision(
        all_in_eur=Decimal("7500"),
        pessimistic_resale_eur=Decimal("8000"),
        optimistic_resale_eur=Decimal("9500"),
    )
    assert sensitive["label"] == "VALUATION_UNRESOLVED"
    assert sensitive["gate_pass"] is False


def test_outlier_does_not_move_the_median_and_sample_size_is_exposed() -> None:
    case = golden()
    case.book = _book(0)
    for index in range(11):
        case.book.append(_obs(index, asking_price_eur=Decimal("18000")))
    case.book.append(_obs(30, asking_price_eur=Decimal("80000")))
    result = value_vehicle_v2(case.identity, case.book, as_of=case.as_of)
    assert result.market_asking_eur == Decimal("18000.00")
    assert result.effective_sample_size >= Decimal("10")
    reasons = " ".join(reason for row in result.rejected for reason in row.reasons)
    assert "Extreme adjusted price" in reasons


def test_future_observation_is_invisible_and_camera_registry_is_unchanged() -> None:
    case = golden()
    case.book.append(_obs(90, observation_id="future", observed_at=AS_OF + timedelta(days=2), asking_price_eur=Decimal("1000")))
    result = value_vehicle_v2(case.identity, case.book, as_of=case.as_of)
    assert result.market_asking_eur == Decimal("18000.00")
    assert "ebay_browse" in {adapter.source_id for adapter in all_adapters()}
    assert "autoza" not in {adapter.source_id for adapter in all_adapters()}
