"""Frozen T426 snapshot lines stay pre-bid and specialists stay off the panel path."""

from app.domains.vehicles.enums import BodyKind
from app.domains.vehicles.ingest.t426_snapshot import body_for_hint, parse_t426_snapshot

_SAMPLE = """
GBP_EUR: 1.1634671321
Cars / vans / 4x4s:
  GBP 0-500: GBP 75
  GBP 4001+: GBP 300
2 | VAN | Ford Transit 290 Trend L2 H2 | 2021-07-12 | FY21 ZWL | 68259 | miles | diesel | 2027-08-14 | Present | Yes | Company Direct | none stated
3 | VAN | Ford Transit workshop van | 2024-01-31 | EK73 VAX | 56138 | miles | diesel | 2027-01-30 | To Follow | Yes | Company Direct | CAT S
17 | CREW_VAN | Ford Transit Custom crew van | 2022-09-16 | XGZ 5940 | 70750 | miles | diesel | 2026-11-06 | To Follow | Yes | Company Direct | none stated
45 | VAN_NON_RUNNER | Peugeot Boxer non-runner | 2021-03-10 | RRZ 9192 | 92760 | miles | diesel | 2027-02-17 | Present | Yes | Company Direct | none stated
"""


def test_snapshot_is_prebid_and_separates_bodies() -> None:
    parsed, fx = parse_t426_snapshot(_SAMPLE)
    assert fx is not None
    assert parsed.sale_code == "T426"
    assert all(lot.current_bid_gbp is None for lot in parsed.lots)
    by_lot = {lot.lot_number: lot for lot in parsed.lots}
    assert by_lot["2"].year == 2021
    assert by_lot["3"].vcar == "CAT S"
    assert body_for_hint("VAN", "Ford Transit 290") is BodyKind.PANEL
    assert body_for_hint("CREW_VAN", "crew van") is BodyKind.CREW
    assert body_for_hint("VAN_NON_RUNNER", "non-runner") is BodyKind.UNKNOWN
    assert body_for_hint("TIPPER", "double cab tipper") is BodyKind.TIPPER
