"""Historical evaluation without lookahead.

Observations after ``as_of`` are invisible. This does not certify accuracy:
there is no historical auction corpus in the repository.
"""

from __future__ import annotations

from datetime import datetime

from app.domains.vehicles.cases import VehicleCase
from app.domains.vehicles.evaluate import Evaluation, evaluate_vehicle
from app.domains.vehicles.market import MarketBook


def evaluate_as_of(case: VehicleCase, as_of: datetime) -> Evaluation:
    blinded = MarketBook()
    for observation in case.book.observations:
        if observation.observed_at <= as_of:
            blinded.append(observation)
    blinded_case = VehicleCase(
        listing=case.listing,
        identity=case.identity,
        as_of=as_of,
        provenance=case.provenance,
        history=case.history,
        book=blinded,
        homologation=case.homologation,
        co2_g_per_km=case.co2_g_per_km,
        co2_basis=case.co2_basis,
        nox_mg_per_km=case.nox_mg_per_km,
        omsp_eur=case.omsp_eur,
        omsp_source=case.omsp_source,
        schedule=case.schedule,
        vat_treatment=case.vat_treatment,
        hammer_includes_vat=case.hammer_includes_vat,
        owner_vat_registered=case.owner_vat_registered,
        commercial_vat_invoice_expected=case.commercial_vat_invoice_expected,
        transport_eur=case.transport_eur,
        transport_posture=case.transport_posture,
        border_transport_eur=case.border_transport_eur,
        insurance_eur=case.insurance_eur,
        payment_fee_eur=case.payment_fee_eur,
        payment_fee_posture=case.payment_fee_posture,
        duty_rate=case.duty_rate,
        preferential_origin_proven=case.preferential_origin_proven,
        registration_fee_eur=case.registration_fee_eur,
        registration_fee_posture=case.registration_fee_posture,
        fx_eur_per_unit=case.fx_eur_per_unit,
        fx_retrieved_at=case.fx_retrieved_at,
        mechanical_inspected=case.mechanical_inspected,
        fuel_override=case.fuel_override,
    )
    return evaluate_vehicle(blinded_case)
