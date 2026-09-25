"""Hard rejects stay off the opportunity list. Unpriced is not 'no headroom'."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.domains.vehicles.ingest.t426_snapshot import parse_t426_snapshot
from app.domains.vehicles.scenarios import catalogue_hard_reject, prebid_economic_group
from pathlib import Path


def _valued(*, floor: bool, stress: str | None, market: str = "MEDIUM") -> SimpleNamespace:
    return SimpleNamespace(
        prebid_floor_available=floor,
        market_floor_confidence=market,
        max_hammer_vat_stress_eur=None if stress is None else Decimal(stress),
        max_hammer_market_floor_eur=None if stress is None else Decimal(stress),
    )


def test_cat_s_and_non_runner_cannot_be_opportunities() -> None:
    text = Path("artifacts/runtime/cv019/T426_CV019_INPUT_2026-09-23.txt").read_text(encoding="utf-8")
    parsed, _fx = parse_t426_snapshot(text)
    lot3 = next(lot for lot in parsed.lots if lot.lot_number == "3")
    lot45 = next(lot for lot in parsed.lots if lot.lot_number == "45")
    valued = _valued(floor=True, stress="10000")
    cat_s = catalogue_hard_reject(title=lot3.title, hint=lot3.vendor_disclosure or "", write_off_label=lot3.vcar or "")
    runner = catalogue_hard_reject(title=lot45.title, hint=lot45.vendor_disclosure or "")
    assert cat_s == "REJECT_WRITE_OFF_CAT_S"
    assert runner == "REJECT_NON_RUNNER"
    assert prebid_economic_group(valued, hard_reject=cat_s) == "REJECT_WRITE_OFF_CAT_S"
    assert prebid_economic_group(valued, hard_reject=runner) == "REJECT_NON_RUNNER"
    assert "OPPORTUNITY" not in prebid_economic_group(valued, hard_reject=cat_s)
    assert "OPPORTUNITY" not in prebid_economic_group(valued, hard_reject=runner)


def test_unpriced_is_not_no_economic_headroom() -> None:
    empty = _valued(floor=False, stress=None, market="LOW")
    assert prebid_economic_group(empty) == "MARKET_INSUFFICIENT"
    attractive = _valued(floor=True, stress="4000")
    assert prebid_economic_group(attractive) == "ECONOMICALLY_INTERESTING_TAX_DILIGENCE"
    resolved = _valued(floor=True, stress="4000")
    resolved.final_max_safe_hammer_eur = Decimal("4000")
    assert prebid_economic_group(resolved) == "ROBUST_OPPORTUNITY"
    unattractive = _valued(floor=True, stress="0")
    assert prebid_economic_group(unattractive) == "NO_ECONOMIC_HEADROOM"
