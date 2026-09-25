"""Dealer stock parsers, VAT enrichment, and dealer-concentration confidence."""

from __future__ import annotations

from decimal import Decimal

from app.domains.vehicles.browser_market.carsireland_dealer import (
    matches_platform,
    parse_carsireland_dealer,
    parse_carsireland_detail,
)
from app.domains.vehicles.browser_market.linders import parse_linders, parse_linders_detail
from app.domains.vehicles.browser_market.terrific import parse_terrific, parse_terrific_detail
from app.domains.vehicles.browser_market.windsor import parse_windsor
from app.domains.vehicles.market_dedupe import assign_duplicate_groups, primary_observations
from app.domains.vehicles.valuation_v3 import value_vehicle_v3
from tests.test_cv_engine import _book, _obs, golden

WINDSOR = """
<script type="application/ld+json">
{"@type":"Car","name":"Peugeot Partner","url":"https://www.windsor.ie/vehicle-details/peugeot/partner/231d44595-peugeot-partner","model":"Partner","vehicleModelDate":2023,"mileageFromOdometer":{"value":41000},"price":"21134.00"}
</script>
<div class="vehicleCard__tagContainer"><p>Price Ex VAT</p><a href="/vehicle-details/peugeot/partner/231d44595-peugeot-partner"><h2>Peugeot Partner</h2></a></div>
<script type="application/ld+json">
{"@type":"Car","name":"Opel Combo Life","url":"https://www.windsor.ie/vehicle-details/opel/combo/life","model":"Combo Life","vehicleModelDate":2021,"price":"18000.00"}
</script>
"""

M3 = """
Powered by CarsIreland.ie
<a href="/car-details/?4548025=2022-ford-transit-custom">2022 Ford Transit Custom</a>
<a href="/car-details/?1=2020-opel-combo-life">2020 Opel Combo Life</a>
<a href="/car-details/?2=2019-ford-transit-tipper">2019 Ford Transit tipper</a>
"""

M3_DETAIL = """
<span class="car-details__price-label">Our Price</span> <span class="car-details__price-value">€21,950</span>
<span class="car-details__price-label">Weekly</span> <span class="car-details__price-value">€93</span>
2022 FORD CUSTOM VAN € 21,950- Price EX VAT
48,000 miles
"""

LINDERS = """
<div class="car-tile"><a href="/vehicle?id=0BpXy"><h2>2020 Citroen Berlingo</h2></a></div>
<div class="car-tile"><a href="/vehicle?id=wav1"><h2>2019 Ford Transit WAV</h2></a></div>
"""

LINDERS_DETAIL = """
<div class="car-page__price"><p>Our Price</p><h3>&euro;20,950</h3></div>
<div class="car-page__price-monthly"><p>Monthly From</p><h3>&euro;399</h3></div>
20950+ 23% Vat
120000 KMS
"""


TERRIFIC = """
<div class="carlistings__car_price">€9,755</div>
<div class="carlistings__car_repayments">From €193 pm</div>
<h2><a href="/used-cars/makes-opel/models-combo/r/opel-combo-2022-swb-1">2022 Opel Combo 1.5 CDTi SWB</a></h2>
<div class="carlistings__car_price">€12,000</div>
<h2><a href="/used-cars/r/combo-life">2021 Opel Combo Life</a></h2>
"""


def test_terrific_ignores_monthly_and_passenger_combo() -> None:
    cards = parse_terrific(TERRIFIC, "https://www.terrific.ie/used-cars/makes-opel/models-combo")
    assert len(cards) == 1
    assert cards[0].asking_price_eur == Decimal("9755")
    assert cards[0].year == 2022
    detail = parse_terrific_detail("85,604 mi / 137,763 km 9755 Plus Vat / 11999 Inc Vat", cards[0])
    assert detail.mileage_km == 137763
    assert detail.vat_classification == "VAT_EXCLUSIVE"


def test_windsor_stock_card_and_ex_vat() -> None:
    cards = parse_windsor(WINDSOR, "https://www.windsor.ie/used-vans")
    assert len(cards) == 1
    card = cards[0]
    assert card.model_family == "partner"
    assert card.year == 2023
    assert card.asking_price_eur == Decimal("21134.00")
    assert card.mileage_km == 41000
    assert card.vat_classification == "VAT_EXCLUSIVE"
    assert card.vat_fragment == "Price Ex VAT"
    assert card.registration == "231D44595"


def test_carsireland_platform_and_passenger_rejection() -> None:
    assert matches_platform(M3)
    cards = parse_carsireland_dealer(M3, "https://www.m3vancentre.ie/used-cars/")
    assert len(cards) == 1
    assert "transit custom" in cards[0].title.lower()
    detail = parse_carsireland_detail(M3_DETAIL, cards[0].url, cards[0])
    assert detail.asking_price_eur == Decimal("21950")
    assert detail.vat_classification == "VAT_EXCLUSIVE"
    assert detail.mileage_km == int(48000 * 1.60934)


def test_linders_uses_our_price_not_monthly() -> None:
    cards = parse_linders(LINDERS, "https://www.linders.ie/search-vans")
    assert len(cards) == 1
    assert cards[0].year == 2020
    detail = parse_linders_detail(LINDERS_DETAIL, cards[0])
    assert detail.asking_price_eur == Decimal("20950")
    assert detail.vat_presentation == "ex_vat"
    assert detail.mileage_km == 120000


def test_dealer_vat_enriches_the_same_physical_comp() -> None:
    carzone = _obs(1, registration="231d44595", vat_presentation="unknown", vat_classification="UNKNOWN", dealer_name="Windsor", mileage_km=41000, asking_price_eur=Decimal("21134"))
    dealer = _obs(2, registration="231d44595", vat_presentation="ex_vat", vat_classification="VAT_EXCLUSIVE", vat_fragment="Price Ex VAT", dealer_name="Windsor", mileage_km=41000, asking_price_eur=Decimal("21134"), source="dealer-windsor")
    merged = primary_observations(assign_duplicate_groups([carzone, dealer]))
    assert len(merged) == 1
    assert merged[0].vat_classification == "VAT_EXCLUSIVE"


def test_one_dealer_cannot_create_medium_confidence() -> None:
    case = golden()
    case.book = _book(0)
    for index in range(12):
        case.book.append(
            _obs(
                index,
                dealer_name="Windsor",
                mileage_km=80000 + index * 4000,
                vat_presentation="unknown",
                vat_classification="UNKNOWN",
                asking_price_eur=Decimal("10000"),
            )
        )
    result = value_vehicle_v3(case.identity, case.book, as_of=case.as_of)
    assert result.dealer_count == 1
    assert result.market_floor_confidence == "LOW"
    assert result.prebid_floor_available is False
    assert result.conservative_eur is None
    mixed = golden()
    mixed.book = _book(0)
    for index in range(10):
        mixed.book.append(_obs(index, mileage_km=80000 + index * 3000, vat_presentation="unknown", vat_classification="UNKNOWN", asking_price_eur=Decimal("10000")))
    mixed.book.append(_obs(20, dealer_name="Windsor", mileage_km=90000, vat_presentation="unknown", vat_classification="UNKNOWN", asking_price_eur=Decimal("10000")))
    mixed_result = value_vehicle_v3(mixed.identity, mixed.book, as_of=mixed.as_of)
    assert mixed_result.market_floor_confidence in {"HIGH", "MEDIUM"}
    assert mixed_result.prebid_floor_available is True
