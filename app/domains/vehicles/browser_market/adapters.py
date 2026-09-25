"""Adapters return the same ListingCard shape."""

from app.domains.vehicles.browser_market.carsireland import SOURCE_ID as CARSIRELAND
from app.domains.vehicles.browser_market.carsireland import parse_carsireland
from app.domains.vehicles.browser_market.carzone import SOURCE_ID as CARZONE
from app.domains.vehicles.browser_market.carzone import parse_carzone
from app.domains.vehicles.browser_market.dealer_generic import SOURCE_ID as DEALER
from app.domains.vehicles.browser_market.dealer_generic import parse_dealer
from app.domains.vehicles.browser_market.donedeal import SOURCE_ID as DONEDEAL
from app.domains.vehicles.browser_market.donedeal import parse_donedeal

ADAPTERS = {
    DONEDEAL: parse_donedeal,
    CARSIRELAND: parse_carsireland,
    CARZONE: parse_carzone,
    DEALER: parse_dealer,
}

__all__ = [
    "ADAPTERS",
    "CARSIRELAND",
    "CARZONE",
    "DEALER",
    "DONEDEAL",
    "parse_carsireland",
    "parse_carzone",
    "parse_dealer",
    "parse_donedeal",
]
