"""Orchestrate identification through maximum bid. No bid is placed."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.core.money import ZERO, money
from app.domains.vehicles.auction_costs import auction_costs
from app.domains.vehicles.cases import VehicleCase
from app.domains.vehicles.enums import (
    BodyKind,
    CandidateState,
    CertificationPosture,
    CommercialClass,
    EvidencePosture,
    ProvenanceState,
)
from app.domains.vehicles.evidence import EvidenceLedger
from app.domains.vehicles.prebid_economics import assess_landed
from app.domains.vehicles.scenarios import catalogue_hard_reject, economic_label, ni_landing_scenarios, prebid_economic_group
from app.domains.vehicles.gates import GateReport, decide_gates
from app.domains.vehicles.history import HistoryAssessment, assess_history
from app.domains.vehicles.identity import apply_vin_consistency
from app.domains.vehicles.landed import LandedCost, stack_landed_cost
from app.domains.vehicles.max_bid import BidEconomics, profit_at, solve_max_hammer
from app.domains.vehicles.owner_documents import note_owner_documents
from app.domains.vehicles.policy import (
    FX_MAX_AGE_DAYS,
    LIQUIDITY_RANK_FACTOR,
    REQUIRED_ABSOLUTE_PROFIT_EUR,
    REQUIRED_ROI,
    SELLING_FRICTION_FLOOR_EUR,
    SELLING_FRICTION_RATE,
    TAX_RULE_MAX_AGE_DAYS,
    TAX_RULES_RETRIEVED_AT,
)
from app.domains.vehicles.provenance import ProvenanceResult, assess_provenance
from app.domains.vehicles.reconditioning import ReconditioningResult, estimate_reconditioning
from app.domains.vehicles.tax import TaxInput, TaxPosition, assess_tax
from app.domains.vehicles.valuation import ValuationResult
from app.domains.vehicles.valuation_v3 import value_vehicle_v3

_GOODS = {BodyKind.PANEL, BodyKind.CHASSIS, BodyKind.TIPPER, BodyKind.DROPSIDE, BodyKind.LUTON}


@dataclass(slots=True)
class RiskItem:
    name: str
    level: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "level": self.level, "detail": self.detail}


@dataclass(slots=True)
class Evaluation:
    state: CandidateState
    certification: CertificationPosture
    purchasing_recommendation: bool
    gates: GateReport
    provenance: ProvenanceResult
    tax: TaxPosition
    valuation: ValuationResult
    repairs: ReconditioningResult
    history: HistoryAssessment
    bid: BidEconomics
    current_bid_eur: Decimal | None
    expected_all_in_eur: Decimal | None
    downside_all_in_eur: Decimal | None
    expected_profit_at_current_eur: Decimal | None
    downside_profit_at_current_eur: Decimal | None
    headroom_eur: Decimal | None
    risks: list[RiskItem]
    owner_actions: list[str]
    why: str
    ledger: EvidenceLedger
    listing_key: str
    vehicle_key: str | None
    title: str
    summary_vehicle: str
    evaluated_at: datetime | None = None
    auction_source: str = ""
    closes_at: str | None = None
    listing_screen: str = ""
    preliminary_max_hammer_eur: Decimal | None = None
    preliminary_note: str = ""

    def _hard_reject_label(self) -> str:
        write_off = ""
        if self.history.write_off is not None and self.history.write_off.outcome.value == "FAIL":
            write_off = self.history.write_off.interpretation
        return catalogue_hard_reject(title=self.title, write_off_label=write_off)

    def _landed(self):
        clear_states = {"ROI_NATIVE", "NI_PRE_2021_PROVEN", "NI_POST_2020_IMPORT_PROVEN"}
        state = self.provenance.state.value
        return assess_landed(
            provenance=state,
            pre_tax_ceiling_eur=self.valuation.max_hammer_vat_stress_eur,
            current_bid_eur=self.current_bid_eur,
            ni_clear_proven=self.provenance.customs_clear and state in clear_states,
            vrt_eur=self.tax.vrt_eur,
            vrt_confirmed=self.tax.vrt_eur is not None and self.tax.vrt_posture.value == "PROVEN",
            homologation_present=False,
            registration_eur=self.tax.registration_eur,
            vat_recovery_posture="UNKNOWN",
        )

    def to_dict(self) -> dict[str, object]:
        landed = self._landed()
        screen = SimpleNamespace(
            prebid_floor_available=self.valuation.prebid_floor_available,
            market_floor_confidence=self.valuation.market_floor_confidence,
            max_hammer_vat_stress_eur=self.valuation.max_hammer_vat_stress_eur,
            max_hammer_market_floor_eur=self.valuation.max_hammer_market_floor_eur,
            final_max_safe_hammer_eur=landed.final_max_safe_hammer_eur,
        )
        return {
            "state": self.state.value,
            "certification": self.certification.value,
            "purchasing_recommendation": self.purchasing_recommendation,
            "does_not_bid": True,
            "prebid_group": prebid_economic_group(screen, hard_reject=self._hard_reject_label()),
            "economics": landed.to_dict(),
            "economic_interest": economic_label(
                state=self.state.value,
                market_pass=bool(self.gates.gates.get("MARKET_EVIDENCE_PASS")),
                auction_cost_pass=bool(self.gates.gates.get("AUCTION_COST_PASS")),
                has_conservative=self.valuation.conservative_eur is not None,
                preliminary_economics=self.listing_screen == "VALUATION_SUFFICIENT",
            ),
            "listing_screen": self.listing_screen,
            "valuation_sufficient": self.listing_screen == "VALUATION_SUFFICIENT",
            "diligence_incomplete": self.state is not CandidateState.BUY_CANDIDATE,
            "buy_ready": self.state is CandidateState.BUY_CANDIDATE,
            "preliminary_max_hammer_eur": _s(self.preliminary_max_hammer_eur),
            "preliminary_note": self.preliminary_note,
            "landing_scenarios": ni_landing_scenarios(self.provenance.state.value),
            "vehicle": self.summary_vehicle,
            "title": self.title,
            "auction": self.auction_source or self.listing_key.split(":", 1)[0],
            "closes_at": self.closes_at,
            "evaluated_at": self.evaluated_at.isoformat() if self.evaluated_at else None,
            "listing_key": self.listing_key,
            "vehicle_key": self.vehicle_key,
            "current_bid_eur": _s(self.current_bid_eur),
            "maximum_safe_bid_eur": _s(self.bid.max_safe_hammer_eur),
            "max_bid_base_eur": _s(self.bid.max_bid_base_eur),
            "max_bid_conservative_eur": _s(self.bid.max_bid_conservative_eur),
            "max_bid_stress_eur": _s(self.bid.max_bid_stress_eur),
            "headroom_eur": _s(self.headroom_eur),
            "expected_all_in_eur": _s(self.expected_all_in_eur),
            "downside_all_in_eur": _s(self.downside_all_in_eur),
            "expected_profit_at_current_eur": _s(self.expected_profit_at_current_eur),
            "downside_profit_at_current_eur": _s(self.downside_profit_at_current_eur),
            "expected_profit_at_max_bid_eur": _s(self.bid.expected_profit_eur),
            "irish_comparable_count": self.valuation.comparable_count,
            "provenance_status": self.provenance.state.value,
            "tax_status": self.tax.vrt_state.value,
            "history_status": self.history.mileage.outcome.value,
            "major_risks": [risk.to_dict() for risk in self.risks if risk.level in {"BLOCKING", "UNKNOWN", "ELEVATED"}],
            "roi_at_max_bid": str(self.bid.roi) if self.bid.roi is not None else None,
            "gates": self.gates.to_dict(),
            "provenance": {
                "state": self.provenance.state.value,
                "customs_clear": self.provenance.customs_clear,
                "interpretation": self.provenance.interpretation,
                "owner_action": self.provenance.owner_action,
            },
            "tax": {
                "rule_version": self.tax.rule_version,
                "vrt_state": self.tax.vrt_state.value,
                "vrt_eur": _s(self.tax.vrt_eur),
                "nox_eur": _s(self.tax.nox_eur),
                "customs_duty_eur": _s(self.tax.customs_duty_eur),
                "import_vat_eur": _s(self.tax.import_vat_eur),
                "registration_eur": _s(self.tax.registration_eur),
                "blocked": self.tax.blocked,
                "notes": list(self.tax.notes),
            },
            "valuation": self.valuation.to_dict(),
            "repairs": {
                "expected_eur": str(self.repairs.expected_eur),
                "downside_eur": str(self.repairs.downside_eur),
                "mechanical_unknown": self.repairs.mechanical_unknown,
                "notes": list(self.repairs.notes),
            },
            "risks": [risk.to_dict() for risk in self.risks],
            "owner_actions": list(self.owner_actions),
            "why": self.why,
            "evidence": self.ledger.to_dict(),
            "bid_note": self.bid.note,
        }


def _s(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _eur(amount: Decimal | None, rate: Decimal | None, currency: str) -> Decimal | None:
    if amount is None:
        return None
    if currency.upper() == "EUR":
        return money(amount)
    if rate is None:
        return None
    return money(amount * rate)


def _effective_class(case: VehicleCase) -> CommercialClass:
    identity = case.identity
    if identity.commercial_class in {CommercialClass.PASSENGER, CommercialClass.PARTS_OR_NOT_A_VEHICLE}:
        return identity.commercial_class
    homologation = case.homologation
    if (
        homologation is not None
        and homologation.eu_category.upper() == "N1"
        and homologation.seats < 4
        and identity.body in _GOODS
    ):
        return CommercialClass.N1_GOODS
    if homologation is not None and homologation.seats >= 4:
        return CommercialClass.CREW_OR_MULTI_SEAT
    if identity.commercial_class is CommercialClass.CREW_OR_MULTI_SEAT:
        return CommercialClass.CREW_OR_MULTI_SEAT
    return CommercialClass.UNKNOWN


def _selling_cost(conservative: Decimal | None) -> Decimal:
    if conservative is None:
        return SELLING_FRICTION_FLOOR_EUR
    return money(max(conservative * SELLING_FRICTION_RATE, SELLING_FRICTION_FLOOR_EUR))


def _fx_fresh(case: VehicleCase) -> bool:
    if case.listing.currency.upper() == "EUR":
        return True
    if case.fx_eur_per_unit is None or case.fx_eur_per_unit <= ZERO or case.fx_retrieved_at is None:
        return False
    age = case.as_of - case.fx_retrieved_at
    return timedelta(0) <= age <= timedelta(days=FX_MAX_AGE_DAYS)


def evaluate_vehicle(case: VehicleCase) -> Evaluation:
    ledger = EvidenceLedger()
    apply_vin_consistency(case.identity, ledger)
    note_owner_documents(case, ledger)
    provenance = assess_provenance(case.provenance, ledger)
    history = assess_history(case.history, ledger)
    repairs = estimate_reconditioning(
        declared_faults=case.history.declared_faults,
        keys=case.history.keys,
        mechanical_inspected=case.mechanical_inspected,
    )
    valuation = value_vehicle_v3(case.identity, case.book, as_of=case.as_of)
    selling = _selling_cost(valuation.conservative_eur)
    currency = case.listing.currency
    rate = Decimal("1") if currency.upper() == "EUR" else case.fx_eur_per_unit
    current = _eur(case.listing.current_bid, rate, currency)

    def tax_for(hammer: Decimal, target: EvidenceLedger) -> TaxPosition:
        customs_value = None
        if provenance.state in {ProvenanceState.GB_ORIGIN, ProvenanceState.GB_TO_NI_UNPROVEN}:
            if case.border_transport_eur is not None and case.insurance_eur is not None:
                customs_value = money(hammer + case.border_transport_eur + case.insurance_eur)
        fuel = case.fuel_override or case.identity.fuel
        return assess_tax(
            TaxInput(
                provenance=provenance.state,
                fuel=fuel,
                seats=case.homologation.seats if case.homologation else case.identity.seats,
                homologation=case.homologation,
                co2_g_per_km=case.co2_g_per_km,
                co2_basis=case.co2_basis,
                nox_mg_per_km=case.nox_mg_per_km,
                omsp_eur=case.omsp_eur,
                omsp_source=case.omsp_source,
                customs_value_eur=customs_value,
                duty_rate=case.duty_rate,
                preferential_origin_proven=case.preferential_origin_proven,
                registration_fee_eur=case.registration_fee_eur,
                registration_fee_posture=case.registration_fee_posture,
            ),
            target,
        )

    def landed_at(hammer: Decimal) -> LandedCost:
        auction = auction_costs(
            hammer_eur=hammer,
            schedule=case.schedule,
            vat_treatment=case.vat_treatment,
            hammer_is_vat_inclusive=case.hammer_includes_vat,
            owner_vat_registered=case.owner_vat_registered,
            commercial_vat_invoice_expected=case.commercial_vat_invoice_expected and _effective_class(case) is CommercialClass.N1_GOODS,
            payment_fee_eur=case.payment_fee_eur,
            payment_fee_posture=case.payment_fee_posture,
            lot_vat_rate=case.auction_lot_vat_rate,
        )
        tax = tax_for(hammer, EvidenceLedger())
        return stack_landed_cost(
            auction=auction,
            tax=tax,
            transport_eur=case.transport_eur,
            transport_posture=case.transport_posture,
            repairs=repairs,
        )

    bid = solve_max_hammer(
        conservative_eur=valuation.conservative_eur,
        quick_sale_eur=valuation.quick_sale_eur,
        selling_cost_eur=selling,
        landed_at=landed_at,
    )
    base_bid = solve_max_hammer(
        conservative_eur=valuation.expected_achievable_eur,
        quick_sale_eur=valuation.conservative_eur,
        selling_cost_eur=selling,
        landed_at=landed_at,
    )
    stress_anchor = money(valuation.conservative_eur * Decimal("0.90")) if valuation.conservative_eur is not None else None
    stress_bid = solve_max_hammer(
        conservative_eur=stress_anchor,
        quick_sale_eur=valuation.quick_sale_eur,
        selling_cost_eur=selling,
        landed_at=landed_at,
    )
    bid = replace(
        bid,
        max_bid_base_eur=base_bid.max_safe_hammer_eur,
        max_bid_conservative_eur=bid.max_safe_hammer_eur,
        max_bid_stress_eur=stress_bid.max_safe_hammer_eur,
    )
    tax = tax_for(current if current is not None else (bid.max_safe_hammer_eur or ZERO), ledger)
    reference_hammer = current if current is not None else bid.max_safe_hammer_eur
    reference = landed_at(reference_hammer) if reference_hammer is not None else None
    expected_profit = None
    downside_profit = None
    if (
        reference is not None
        and reference.expected_all_in_eur is not None
        and reference.downside_all_in_eur is not None
        and valuation.expected_achievable_eur is not None
        and valuation.quick_sale_eur is not None
    ):
        expected_profit = profit_at(
            resale_eur=valuation.expected_achievable_eur,
            selling_cost_eur=selling,
            all_in_eur=reference.expected_all_in_eur,
        )
        downside_profit = profit_at(
            resale_eur=valuation.quick_sale_eur,
            selling_cost_eur=selling,
            all_in_eur=reference.downside_all_in_eur,
        )
    bid_ignored = case.listing.current_bid is not None and current is None
    price_ok = (
        not bid_ignored
        and bid.max_safe_hammer_eur is not None
        and not bid.blocked
        and (current is None or current <= bid.max_safe_hammer_eur)
    )
    # Hurdles are tested at the solved maximum, where conservative profit is tightest.
    # A higher current bid fails PRICE_PASS without pretending the economics were never viable.
    profit_ok = (
        not bid.blocked
        and bid.expected_profit_eur is not None
        and bid.roi is not None
        and bid.expected_profit_eur >= REQUIRED_ABSOLUTE_PROFIT_EUR
        and bid.roi >= REQUIRED_ROI
    )
    downside_ok = bid.downside_profit_eur is not None and bid.downside_profit_eur >= ZERO
    tax_age = case.as_of - TAX_RULES_RETRIEVED_AT
    tax_fresh = timedelta(0) <= tax_age <= timedelta(days=TAX_RULE_MAX_AGE_DAYS)
    fresh_ok = valuation.fresh and tax_fresh and _fx_fresh(case) and not bid_ignored
    vin_conflict = any(record.status == "MANUFACTURER_CONFLICT" for record in ledger.records)
    identity_ok = bool(case.identity.manufacturer and case.identity.model_family and case.identity.vin) and not vin_conflict
    commercial = _effective_class(case)
    hard_reject = (
        commercial in {CommercialClass.PASSENGER, CommercialClass.PARTS_OR_NOT_A_VEHICLE}
        or history.mileage.outcome.value == "FAIL"
        or history.stolen.outcome.value == "FAIL"
        or history.write_off.outcome.value == "FAIL"
        or vin_conflict
        or _explicit_non_runner(case)
    )
    auction_probe = auction_costs(
        hammer_eur=current or ZERO,
        schedule=case.schedule,
        vat_treatment=case.vat_treatment,
        hammer_is_vat_inclusive=case.hammer_includes_vat,
        owner_vat_registered=case.owner_vat_registered,
        commercial_vat_invoice_expected=case.commercial_vat_invoice_expected and commercial is CommercialClass.N1_GOODS,
        payment_fee_eur=case.payment_fee_eur,
        payment_fee_posture=case.payment_fee_posture,
        lot_vat_rate=case.auction_lot_vat_rate,
    )
    report = decide_gates(
        identity_ok=identity_ok,
        commercial_class=commercial,
        history=history,
        provenance=provenance,
        tax=tax,
        auction_blocked=auction_probe.blocked,
        valuation=valuation,
        condition_ok=case.mechanical_inspected and not repairs.mechanical_unknown,
        reconditioning_ok=repairs.expected_eur is not None and repairs.downside_eur >= repairs.expected_eur,
        downside_ok=downside_ok,
        profit_ok=profit_ok,
        fresh_ok=fresh_ok,
        price_ok=price_ok,
        hard_reject=hard_reject,
        economics_blocked=bid.blocked or tax.blocked,
    )
    headroom = None
    if current is not None and bid.max_safe_hammer_eur is not None:
        headroom = money(bid.max_safe_hammer_eur - current)
    actions = _actions(provenance, report, case)
    risks = _risks(
        provenance,
        tax,
        valuation,
        repairs,
        history,
        fresh_ok,
        vin_conflict,
        has_vin=bool(case.identity.vin),
    )
    why = _why(report)
    preliminary_hammer, preliminary_note = _payment_fee_reserve(case, valuation, selling, landed_at)
    valuation = _attach_screening_hammers(case, valuation, repairs, tax_for, landed_at)
    return Evaluation(
        state=report.state,
        certification=CertificationPosture.SHADOW,
        purchasing_recommendation=False,
        gates=report,
        provenance=provenance,
        tax=tax,
        valuation=valuation,
        repairs=repairs,
        history=history,
        bid=bid,
        current_bid_eur=current,
        expected_all_in_eur=None if reference is None else reference.expected_all_in_eur,
        downside_all_in_eur=None if reference is None else reference.downside_all_in_eur,
        expected_profit_at_current_eur=expected_profit,
        downside_profit_at_current_eur=downside_profit,
        headroom_eur=headroom,
        risks=risks,
        owner_actions=actions,
        why=why,
        ledger=ledger,
        listing_key=case.listing.listing_key,
        vehicle_key=case.identity.vehicle_key,
        title=case.listing.title,
        summary_vehicle=_summary(case),
        evaluated_at=case.as_of,
        auction_source=case.listing.source_id,
        closes_at=case.listing.ends_at.isoformat() if case.listing.ends_at else None,
        listing_screen="VALUATION_SUFFICIENT" if listing_identity_sufficient(case) and valuation.conservative_eur is not None else "LISTING_IDENTITY_INCOMPLETE",
        preliminary_max_hammer_eur=preliminary_hammer,
        preliminary_note=preliminary_note,
    )


def _attach_screening_hammers(case: VehicleCase, valuation: ValuationResult, repairs: ReconditioningResult, tax_for, landed_at) -> ValuationResult:
    """Screening hammers use labelled cash proceeds. Unresolved purchase tax is excluded, not zeroed."""

    from app.core.config import settings
    from app.domains.vehicles.evidence import MoneyLine

    if not valuation.prebid_floor_available or valuation.conservative_eur is None or valuation.quick_sale_eur is None:
        return valuation
    selling = _selling_cost(valuation.conservative_eur)

    def screening_landed(hammer: Decimal) -> LandedCost:
        fee = case.payment_fee_eur
        posture = case.payment_fee_posture
        if posture is EvidencePosture.UNKNOWN or fee is None:
            fee = money(hammer * Decimal(str(settings.payment_fee_percent)) + Decimal(str(settings.payment_fee_fixed_eur)))
            posture = EvidencePosture.ESTIMATED
        auction = auction_costs(
            hammer_eur=hammer,
            schedule=case.schedule,
            vat_treatment=case.vat_treatment,
            hammer_is_vat_inclusive=case.hammer_includes_vat,
            owner_vat_registered=case.owner_vat_registered,
            commercial_vat_invoice_expected=case.commercial_vat_invoice_expected and _effective_class(case) is CommercialClass.N1_GOODS,
            payment_fee_eur=fee,
            payment_fee_posture=posture,
            lot_vat_rate=case.auction_lot_vat_rate,
        )
        lines = [line for line in auction.lines if line.name != "auction_lot_vat_cash"]
        if case.transport_posture is not EvidencePosture.UNKNOWN and case.transport_eur is not None:
            lines.append(MoneyLine("transport", case.transport_eur, case.transport_posture, "logistics", "Collection and delivery."))
        lines.append(MoneyLine("reconditioning", repairs.expected_eur, repairs.posture, "reconditioning", "Expected reserve"))
        blocked = auction.blocked or any(line.amount_eur is None or line.posture is EvidencePosture.UNKNOWN for line in lines)
        total = None if blocked else money(sum((line.amount_eur for line in lines if line.amount_eur is not None), ZERO))
        return LandedCost(total, total, blocked, tuple(lines))

    market = solve_max_hammer(
        conservative_eur=valuation.conservative_eur,
        quick_sale_eur=valuation.quick_sale_eur,
        selling_cost_eur=selling,
        landed_at=screening_landed,
    )
    stress_proceeds = valuation.vat_stress_proceeds_eur
    stress_quick = None
    if stress_proceeds is not None and valuation.conservative_eur > ZERO:
        stress_quick = money(stress_proceeds * (valuation.quick_sale_eur / valuation.conservative_eur))
    stress = solve_max_hammer(
        conservative_eur=stress_proceeds,
        quick_sale_eur=stress_quick,
        selling_cost_eur=_selling_cost(stress_proceeds) if stress_proceeds is not None else selling,
        landed_at=screening_landed,
    )
    market_hammer = market.max_safe_hammer_eur
    stress_hammer = stress.max_safe_hammer_eur
    if market_hammer is not None and stress_hammer is not None and stress_hammer > market_hammer:
        stress_hammer = market_hammer
    confirmed = None
    probe = tax_for(market_hammer or ZERO, EvidenceLedger())
    if not probe.blocked:
        confirmed = solve_max_hammer(
            conservative_eur=valuation.conservative_eur,
            quick_sale_eur=valuation.quick_sale_eur,
            selling_cost_eur=selling,
            landed_at=landed_at,
        ).max_safe_hammer_eur
    return replace(
        valuation,
        max_hammer_market_floor_eur=market_hammer,
        max_hammer_vat_stress_eur=stress_hammer,
        max_hammer_confirmed_tax_eur=confirmed,
    )


def _payment_fee_reserve(case: VehicleCase, valuation: ValuationResult, selling: Decimal, landed_at) -> tuple[Decimal | None, str]:
    if case.payment_fee_posture is not EvidencePosture.UNKNOWN or valuation.conservative_eur is None or case.schedule is None:
        return None, ""
    from app.core.config import settings

    percent = Decimal(str(settings.payment_fee_percent))
    fixed = Decimal(str(settings.payment_fee_fixed_eur))

    def reserved(hammer: Decimal) -> LandedCost:
        fee = money(hammer * percent + fixed)
        auction = auction_costs(
            hammer_eur=hammer,
            schedule=case.schedule,
            vat_treatment=case.vat_treatment,
            hammer_is_vat_inclusive=case.hammer_includes_vat,
            owner_vat_registered=case.owner_vat_registered,
            commercial_vat_invoice_expected=case.commercial_vat_invoice_expected and _effective_class(case) is CommercialClass.N1_GOODS,
            payment_fee_eur=fee,
            payment_fee_posture=EvidencePosture.ESTIMATED,
            lot_vat_rate=case.auction_lot_vat_rate,
        )
        return stack_landed_cost(
            auction=auction,
            tax=landed_at(hammer).tax if False else _tax_only(case, hammer, valuation),
            transport_eur=case.transport_eur,
            transport_posture=case.transport_posture,
            repairs=estimate_reconditioning(
                declared_faults=case.history.declared_faults,
                keys=case.history.keys,
                mechanical_inspected=case.mechanical_inspected,
            ),
        )

    del landed_at
    solved = solve_max_hammer(
        conservative_eur=valuation.conservative_eur,
        quick_sale_eur=valuation.quick_sale_eur,
        selling_cost_eur=selling,
        landed_at=reserved,
    )
    note = "UNKNOWN PAYMENT METHOD FEE. Preliminary hammer uses the configured payment reserve and does not pass the auction-cost gate."
    return solved.max_safe_hammer_eur, note


def _tax_only(case: VehicleCase, hammer: Decimal, valuation: ValuationResult) -> TaxPosition:
    del valuation
    from app.domains.vehicles.tax import TaxInput, assess_tax
    from app.domains.vehicles.provenance import assess_provenance

    provenance = assess_provenance(case.provenance, EvidenceLedger())
    return assess_tax(
        TaxInput(
            provenance=provenance.state,
            fuel=case.fuel_override or case.identity.fuel,
            seats=case.homologation.seats if case.homologation else case.identity.seats,
            homologation=case.homologation,
            co2_g_per_km=case.co2_g_per_km,
            co2_basis=case.co2_basis,
            nox_mg_per_km=case.nox_mg_per_km,
            omsp_eur=case.omsp_eur,
            omsp_source=case.omsp_source,
            duty_rate=case.duty_rate,
            preferential_origin_proven=case.preferential_origin_proven,
            registration_fee_eur=case.registration_fee_eur,
            registration_fee_posture=case.registration_fee_posture,
        ),
        EvidenceLedger(),
    )


def _explicit_non_runner(case: VehicleCase) -> bool:
    text = " ".join(case.history.declared_faults).lower()
    return "non-runner" in text or "non runner" in text


def listing_identity_sufficient(case: VehicleCase) -> bool:
    identity = case.identity
    return bool(identity.manufacturer and identity.model_family and identity.year and identity.mileage_km and identity.body)


def _summary(case: VehicleCase) -> str:
    identity = case.identity
    parts = [
        str(identity.year or ""),
        identity.manufacturer or "unknown make",
        (identity.model_family or "unknown model").replace("_", " "),
        identity.body.value,
        identity.fuel.value,
    ]
    return " ".join(part for part in parts if part).strip()


def _actions(provenance: ProvenanceResult, report: GateReport, case: VehicleCase) -> list[str]:
    actions: list[str] = []
    if provenance.owner_action:
        actions.append(provenance.owner_action)
    failed = set(report.failures)
    if "VRT_MODEL_PASS" in failed or "COMMERCIAL_CLASS_PASS" in failed:
        actions.append(
            "Obtain the Certificate of Conformity, NSSTA, or IVA showing EU category, seat count, mass in service, and technically permissible maximum laden mass."
        )
    if "HISTORY_PASS" in failed or "MILEAGE_PASS" in failed:
        actions.append("Obtain MOT or NCT history, and a finance, stolen, and write-off check tied to this VIN from a source that can return a clear result.")
    if "MARKET_EVIDENCE_PASS" in failed or "VALUATION_CONFIDENCE_PASS" in failed or "LIQUIDITY_PASS" in failed:
        actions.append("Do not treat the asking prices in this file as a sale. Refresh Irish comps for this exact derivative before bidding.")
    if "AUCTION_COST_PASS" in failed:
        actions.append("Confirm this catalogue's buyer premium, premium VAT, lot VAT treatment, and whether the bid is VAT-inclusive.")
    if case.listing.currency.upper() != "EUR" and not _fx_fresh(case):
        actions.append("Apply a fresh EUR conversion rate before using any sterling figure.")
    if report.state is CandidateState.BUY_CANDIDATE:
        actions.append("Shadow result only. Inspect the van, documents, and VAT invoice before any bid. ARIE-CV will not bid.")
    # De-duplicate while keeping order.
    seen: set[str] = set()
    unique: list[str] = []
    for action in actions:
        if action not in seen:
            seen.add(action)
            unique.append(action)
    return unique


def _risks(
    provenance: ProvenanceResult,
    tax: TaxPosition,
    valuation: ValuationResult,
    repairs: ReconditioningResult,
    history: HistoryAssessment,
    fresh_ok: bool,
    vin_conflict: bool,
    has_vin: bool,
) -> list[RiskItem]:
    def level(blocking: bool, unknown: bool) -> str:
        if blocking:
            return "BLOCKING"
        if unknown:
            return "UNKNOWN"
        return "LOW"

    return [
        RiskItem(
            "identity",
            "BLOCKING" if vin_conflict or not has_vin else "LOW",
            "A VIN is required. A WMI hint is only a consistency check.",
        ),
        RiskItem("documentation", level(False, history.finance.outcome.value == "NOT_CHECKED"), history.finance.interpretation),
        RiskItem("provenance", level(not provenance.customs_clear, provenance.state is ProvenanceState.UNKNOWN), provenance.interpretation),
        RiskItem("tax", "BLOCKING" if tax.blocked else "LOW", tax.vrt_state.value),
        RiskItem("mechanical", "BLOCKING" if repairs.mechanical_unknown else "LOW", "Inspection flag and declared faults."),
        RiskItem("condition", "ELEVATED" if repairs.expected_eur > ZERO else "LOW", f"Expected reserve €{repairs.expected_eur}."),
        RiskItem("valuation", "UNKNOWN" if valuation.expected_achievable_eur is None else "ELEVATED", f"Confidence {valuation.confidence}."),
        RiskItem("liquidity", valuation.liquidity.classification.value, valuation.liquidity.interpretation),
        RiskItem("market", "BLOCKING" if not valuation.fresh else "LOW", "Freshness window applied to Irish observations."),
        RiskItem("data_freshness", "BLOCKING" if not fresh_ok else "LOW", "Tax-rule age, market age, and FX age."),
        RiskItem("auction", "UNKNOWN", "Fee schedule and VAT treatment are source-specific."),
    ]


def _why(report: GateReport) -> str:
    if report.state is CandidateState.BUY_CANDIDATE:
        return (
            "Every fail-closed gate passed on the evidence supplied. "
            "This is a shadow candidate, not a certified purchasing instruction."
        )
    if not report.failures:
        return report.state.value
    return "Did not survive because: " + ", ".join(report.failures) + "."


def rank_candidates(evaluations: list[Evaluation]) -> list[Evaluation]:
    """Explainable sort: risk-adjusted profit, then headroom, then confidence, then liquidity."""

    def key(ev: Evaluation) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        profit = ev.expected_profit_at_current_eur or ZERO
        factor = LIQUIDITY_RANK_FACTOR[ev.valuation.liquidity.classification.value]
        adjusted = profit * ev.valuation.confidence * factor
        headroom = ev.headroom_eur or ZERO
        return (adjusted, headroom, ev.valuation.confidence, factor)

    return sorted(evaluations, key=key, reverse=True)
