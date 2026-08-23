"""Scan pipeline: ingest → identify → value → cost → decide."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.certification.engine import category_is_certified
from app.comps.matcher import match_comp
from app.condition.category import assess_category_condition
from app.condition.engine import assess_condition
from app.core.config import settings
from app.core.logging import get_logger
from app.core.money import ZERO, as_decimal, money
from app.costs.landed import compute_landed_cost
from app.decision.gates import apply_money_ready_gates
from app.discovery.mispricing import mispricing
from app.economics.ev import expected_value
from app.economics.negotiate import negotiation_targets
from app.economics.urgency import classify_urgency
from app.exits.engine import compare_exits
from app.identity.engine import identify_listing
from app.identity.resolvers import identify_with_resolvers
from app.liquidity.engine import estimate_liquidity
from app.lots.engine import split_lot
from app.models.enums import EvidenceType, SourceStatus
from app.models.orm import (
    Comparable,
    FxRate,
    Listing,
    Opportunity,
    Product,
    RawListing,
    ScanJob,
    Source,
    SourceHealth,
    Valuation,
)
from app.observability.metrics import record_metric
from app.observations.tracker import record_observation
from app.opportunity.engine import score_opportunity
from app.paper.service import open_paper_trade
from app.risk.engine import assess_risk
from app.shipping.engine import estimate_inbound, estimate_outbound
from app.sold.provider import search_sold_evidence
from app.sources.base import HealthProof, NormalizedListing
from app.sources.ecb import EcbFxAdapter
from app.sources.registry import adapter_map, all_adapters
from app.sources.scryfall import ScryfallAdapter
from app.tax.irish import estimate_acquisition_tax
from app.tax.scenarios import scenario_matrix
from app.valuation.engine import Comp, value_from_comps
from app.valuation.irish import corridor_for, to_eur

logger = get_logger("arie.pipeline")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fingerprint(source_id: str, external_id: str, url: str) -> str:
    return hashlib.sha256(f"{source_id}|{external_id}|{url}".encode()).hexdigest()


def _d(name: str) -> Decimal:
    return as_decimal(getattr(settings, name))


def seed_sources(session: Session) -> None:
    """Upsert registry rows so the dashboard always has a source list."""
    existing = {row.id for row in session.scalars(select(Source)).all()}
    for adapter in all_adapters():
        if adapter.source_id in existing:
            if adapter.source_id == "ebay_browse":
                row = session.get(Source, adapter.source_id)
                if row is not None:
                    row.commercial_quality = "LOW" if settings.ebay_api_env == "sandbox" else row.commercial_quality
            continue
        session.add(
            Source(
                id=adapter.source_id,
                display_name=adapter.display_name,
                country=adapter.country,
                kind=adapter.kind.value,
                official_api=adapter.official_api,
                access_method=adapter.access_method,
                credentials_required=adapter.credentials_required,
                status=SourceStatus.DISABLED.value,
                status_reason="Not health-checked yet.",
                cadence_minutes=adapter.cadence_minutes,
                enabled=adapter.source_id in settings.source_ids()
                or adapter.source_id in {"csv_import", "manual", "ecb_fx"},
                commercial_quality=(
                    "LOW"
                    if adapter.source_id == "scryfall"
                    or (adapter.source_id == "ebay_browse" and settings.ebay_api_env == "sandbox")
                    else "UNKNOWN"
                ),
            )
        )
    session.flush()


async def record_health(session: Session, source_id: str | None = None) -> list[HealthProof]:
    proofs: list[HealthProof] = []
    adapters = all_adapters() if source_id is None else [adapter_map()[source_id]]
    by_id = {row.id: row for row in session.scalars(select(Source)).all()}
    for adapter in adapters:
        proof = await adapter.healthcheck()
        proofs.append(proof)
        row = by_id.get(adapter.source_id)
        if row is None:
            continue
        row.status = proof.status.value
        row.status_reason = proof.detail
        if proof.ok:
            row.last_success_at = proof.checked_at
            row.last_proof_at = proof.checked_at
            row.records_ingested = (row.records_ingested or 0) + proof.records
            row.last_error = None
        else:
            row.last_error_at = proof.checked_at
            row.last_error = proof.detail
        session.add(
            SourceHealth(
                source_id=adapter.source_id,
                status=proof.status.value,
                http_status=proof.http_status,
                latency_ms=proof.latency_ms,
                records=proof.records,
                detail=proof.detail,
                proof=proof.proof,
            )
        )
    session.flush()
    return proofs


async def refresh_fx(session: Session) -> dict[str, Decimal]:
    adapter = EcbFxAdapter()
    rates, as_of = await adapter.fetch_rates()
    for code, rate in rates.items():
        existing = session.scalar(
            select(FxRate).where(FxRate.base == "EUR", FxRate.quote == code, FxRate.as_of == as_of)
        )
        if existing is None:
            session.add(FxRate(base="EUR", quote=code, rate=rate, as_of=as_of, source="ecb_fx"))
        else:
            existing.rate = rate
    session.flush()
    return rates


def _eur_per_unit(rates: dict[str, Decimal], currency: str) -> Decimal:
    currency = currency.upper()
    if currency == "EUR":
        return Decimal("1")
    units = rates.get(currency)
    if not units or units == 0:
        return Decimal("1")
    return Decimal("1") / units


def persist_listing(session: Session, item: NormalizedListing) -> Listing:
    fp = _fingerprint(item.source_id, item.external_id, item.url)
    raw = session.scalar(
        select(RawListing).where(
            RawListing.source_id == item.source_id,
            RawListing.external_id == item.external_id,
        )
    )
    if raw is None:
        raw = RawListing(
            source_id=item.source_id,
            external_id=item.external_id,
            url=item.url,
            fetched_at=item.observed_at,
            payload=item.raw,
            content_hash=fp,
        )
        session.add(raw)
        session.flush()
    listing = session.scalar(
        select(Listing).where(
            Listing.source_id == item.source_id,
            Listing.external_id == item.external_id,
        )
    )
    identity = identify_with_resolvers(
        title=item.title,
        description=item.description,
        brand_hint=item.brand,
        model_hint=item.model,
        gtin=item.gtin,
        mpn=item.mpn,
        category=item.category,
    )
    condition = assess_category_condition(item.condition_raw, item.description, identity.category or item.category)
    if listing is None:
        listing = Listing(
            source_id=item.source_id,
            raw_listing_id=raw.id,
            external_id=item.external_id,
            url=item.url,
            title=item.title,
            description=item.description,
            seller=item.seller,
            seller_type=item.seller_type,
            seller_location=item.seller_location,
            country=item.country,
            currency=item.currency,
            asking_price=item.asking_price,
            current_bid=item.current_bid,
            buy_now_price=item.buy_now_price,
            shipping_cost=item.shipping_cost,
            shipping_currency=item.shipping_currency,
            condition_raw=item.condition_raw,
            condition_grade=condition.grade.value,
            category=item.category or identity.category,
            brand=identity.brand or item.brand,
            model=identity.model or item.model,
            variant=identity.variant,
            gtin=identity.gtin,
            mpn=identity.mpn,
            listing_type=item.listing_type,
            first_seen_at=item.observed_at,
            last_seen_at=item.observed_at,
            observed_at=item.observed_at,
            fingerprint=fp,
            source_confidence=item.source_confidence,
            extras=item.extras,
            images=item.images,
        )
        session.add(listing)
    else:
        listing.title = item.title
        listing.asking_price = item.asking_price
        listing.shipping_cost = item.shipping_cost
        listing.last_seen_at = item.observed_at
        listing.observed_at = item.observed_at
        listing.images = item.images or listing.images
    session.flush()

    product = session.scalar(select(Product).where(Product.canonical_key == identity.canonical_key))
    if product is None:
        product = Product(
            canonical_key=identity.canonical_key,
            brand=identity.brand,
            family=identity.family,
            model=identity.model,
            variant=identity.variant,
            category=identity.category,
            gtin=identity.gtin,
            mpn=identity.mpn,
            identity_level=identity.level.value,
            identity_confidence=identity.confidence,
            attributes={"storage": identity.storage, "is_lot": identity.is_lot},
        )
        session.add(product)
        session.flush()
    listing.product_id = product.id
    listing._identity = identity  # type: ignore[attr-defined]
    listing._condition = condition  # type: ignore[attr-defined]
    return listing


async def _comps_for(listing: Listing, rates: dict[str, Decimal], session=None) -> list[Comp]:
    comps: list[Comp] = []
    identity = getattr(listing, "_identity", None)
    is_card = listing.category == "trading_cards" or (identity and getattr(identity, "category", None) == "trading_cards")
    fx = _eur_per_unit(rates, listing.currency)
    query = (listing.model or listing.title or "")[:80]
    if session is not None:
        try:
            sold = await search_sold_evidence(session, query, listing.country or "IE", listing.condition_grade or "")
            for hit in sold:
                verdict = match_comp(listing.title, hit.title)
                if not verdict.accepted:
                    continue
                comps.append(
                    Comp(
                        source=hit.source,
                        url=hit.url,
                        title=hit.title,
                        price_eur=hit.sold_price_eur,
                        evidence_type=hit.evidence_type,
                        country=hit.territory,
                        condition_score=Decimal("0.85"),
                        product_score=verdict.identity_similarity,
                        observed_at=hit.sold_date,
                        notes=hit.notes,
                    )
                )
        except Exception as exc:
            logger.warning("sold_evidence_failed", error=str(exc))
    # Comparable-source guides (Scryfall) *are* the evidence. Acquisition asks are not.
    if listing.source_id == "scryfall" and listing.asking_price is not None:
        comps.append(
            Comp(
                source="scryfall",
                url=listing.url,
                title=listing.title,
                price_eur=to_eur(listing.asking_price, listing.currency, fx),
                evidence_type=EvidenceType.DEALER_RETAIL,
                country="EU",
                condition_score=Decimal("0.70"),
                product_score=Decimal("1.00"),
                observed_at=listing.observed_at,
                notes="Subject Cardmarket EUR guide via Scryfall. Dealer/market, not an Irish realised sale.",
            )
        )
    if not is_card:
        try:
            from app.sources.reverb import ReverbAdapter

            peers = await ReverbAdapter().search(query, limit=8)
            for peer in peers:
                if not peer.asking_price or peer.url == listing.url:
                    continue
                if not match_comp(listing.title, peer.title).accepted:
                    continue
                peer_fx = _eur_per_unit(rates, peer.currency) if peer.currency else fx
                comps.append(
                    Comp(
                        source="reverb",
                        url=peer.url,
                        title=peer.title,
                        price_eur=to_eur(peer.asking_price, peer.currency, peer_fx),
                        evidence_type=EvidenceType.CURRENT_ASKING,
                        country=peer.country or "UN",
                        condition_score=Decimal("0.80"),
                        product_score=Decimal("0.75"),
                        observed_at=peer.observed_at,
                        notes="Peer Reverb asking price. Not a realised Irish sale.",
                    )
                )
        except Exception as exc:
            logger.warning("peer_reverb_comp_failed", error=str(exc))
    if is_card and query:
        try:
            q = f'!"{query}"' if " " in query else query
            cards = await ScryfallAdapter().search(q, limit=8)
            for card in cards:
                if not card.asking_price or card.url == listing.url:
                    continue
                comps.append(
                    Comp(
                        source="scryfall",
                        url=card.url,
                        title=card.title,
                        price_eur=card.asking_price,
                        evidence_type=EvidenceType.DEALER_RETAIL,
                        country="EU",
                        condition_score=Decimal("0.70"),
                        product_score=Decimal("0.85"),
                        observed_at=card.observed_at,
                        notes="Peer Cardmarket EUR guide via Scryfall. Dealer/market, not Irish realised.",
                    )
                )
        except Exception as exc:
            logger.warning("scryfall_comp_failed", error=str(exc))
    return comps


def evaluate_listing(
    session: Session,
    listing: Listing,
    comps: list[Comp],
    rates: dict[str, Decimal],
) -> Opportunity:
    identity = getattr(listing, "_identity", None) or identify_with_resolvers(
        title=listing.title, description=listing.description, category=listing.category
    )
    condition = getattr(listing, "_condition", None) or assess_category_condition(
        listing.condition_raw, listing.description, listing.category
    )
    valuation = value_from_comps(comps)
    fx = _eur_per_unit(rates, listing.currency)
    purchase = listing.asking_price or listing.current_bid or ZERO
    corridor = corridor_for(listing.country)
    tax = estimate_acquisition_tax(
        corridor=corridor,
        customs_value_eur=to_eur(purchase, listing.currency, fx),
        seller_vat_registered=None,
        goods_are_second_hand=condition.grade.value not in {"new"},
        owner_vat_registered=settings.owner_vat_registered,
        owner_uses_margin_scheme=settings.owner_uses_margin_scheme,
        vat_rate=_d("vat_rate"),
    )
    inbound = estimate_inbound(
        corridor=corridor,
        listed=to_eur(listing.shipping_cost, listing.shipping_currency or listing.currency, fx)
        if listing.shipping_cost is not None
        else None,
        category=listing.category or identity.category,
    )
    outbound = estimate_outbound(category=listing.category or identity.category, channel="ebay_ie")
    shipping = inbound.amount_eur
    costs = compute_landed_cost(
        purchase_price=purchase,
        currency_to_eur=fx,
        corridor=corridor,
        shipping_listed=shipping,
        expected_resale_eur=valuation.expected_sale_eur,
        quick_sale_eur=valuation.quick_sale_eur,
        high_sale_eur=valuation.high_eur,
        vat_rate=_d("vat_rate"),
        payment_fee_rate=_d("payment_fee_percent"),
        payment_fee_fixed=_d("payment_fee_fixed_eur"),
        platform_fee_rate=_d("ebay_ie_final_value_fee"),
        platform_fee_vat=_d("ebay_ie_fee_vat"),
        returns_allowance=_d("returns_allowance"),
        warranty_allowance=_d("warranty_allowance"),
        refurb_eur=condition.refurb_low_eur,
        duty_eur=tax.duty_eur,
        import_vat_eur=tax.import_vat_eur,
        fx_spread=_d("fx_spread"),
        target_margin_percent=_d("target_margin_percent"),
        risk_percent=_d("risk_percent"),
        listing_type=listing.listing_type,
        outbound_shipping=outbound.amount_eur + outbound.insurance_eur + outbound.packaging_eur,
    )
    exits = compare_exits(
        expected_sale_eur=valuation.expected_sale_eur,
        category=listing.category or identity.category,
    )
    best_quote = next((q for q in exits.quotes if q.channel == exits.best_expected_exit), exits.quotes[0])
    # Recompute net from the best exit rather than a single generic fee.
    costs.expected_net_resale_eur = best_quote.net_proceeds
    costs.expected_profit_eur = money(best_quote.net_proceeds - costs.all_in_acquisition_eur)
    costs.roi = money(costs.expected_profit_eur / costs.all_in_acquisition_eur) if costs.all_in_acquisition_eur else ZERO
    lot = split_lot(listing.title, listing.description)
    liquidity = estimate_liquidity(
        comparable_count=valuation.comparable_count,
        realised_count=valuation.realised_count,
        local_count=valuation.local_count,
        category=listing.category,
        is_lot=lot.is_lot,
    )
    risk = assess_risk(
        title=listing.title,
        identity_level=identity.level,
        identity_confidence=identity.confidence,
        condition_confidence=condition.confidence,
        valuation_confidence=valuation.confidence,
        asking_eur=costs.purchase_price_eur,
        expected_sale_eur=valuation.expected_sale_eur,
        seller=listing.seller,
        images=listing.images or [],
        is_lot=lot.is_lot,
    )
    ends_in = None
    if listing.ends_at:
        ends_in = max(0.0, (listing.ends_at - _now()).total_seconds() / 3600)
    decision = score_opportunity(
        expected_profit=costs.expected_profit_eur,
        roi=costs.roi,
        expected_days=liquidity.expected_days_to_sale,
        valuation_confidence=valuation.confidence,
        identity_confidence=identity.confidence,
        condition_confidence=condition.confidence,
        liquidity_score=liquidity.score,
        downside_profit=costs.downside_profit_eur,
        risk_score=risk.score,
        identity_level=identity.level,
        ends_in_hours=ends_in,
        min_profit=_d("min_profit_eur"),
        min_roi=_d("min_roi"),
        min_confidence=_d("min_confidence"),
        max_days=settings.max_days_to_sale,
        max_capital=_d("max_capital_per_item_eur"),
        capital_required=costs.all_in_acquisition_eur,
        asking=costs.purchase_price_eur,
        max_buy=costs.max_purchase_eur,
    )
    age_hours = (_now() - listing.observed_at).total_seconds() / 3600 if listing.observed_at else 0
    gates = apply_money_ready_gates(
        engine=decision.decision,
        identity_level=identity.level,
        identity_confidence=identity.confidence,
        condition_confidence=condition.confidence,
        valuation_confidence=valuation.confidence,
        comparable_count=valuation.comparable_count,
        realised_count=valuation.realised_count,
        local_count=valuation.local_count,
        liquidity_confidence=liquidity.liquidity_confidence,
        expected_days=liquidity.expected_days_to_sale,
        expected_profit=costs.expected_profit_eur,
        downside_profit=costs.downside_profit_eur,
        roi=costs.roi,
        risk_score=risk.score,
        high_risk=risk.high,
        asking=costs.purchase_price_eur,
        max_buy=costs.max_purchase_eur,
        all_in_cost=costs.all_in_acquisition_eur,
        purchase_price=costs.purchase_price_eur,
        gross_sale=costs.expected_resale_eur,
        net_proceeds=costs.expected_net_resale_eur,
        category=listing.category or identity.category,
        category_certified=category_is_certified(listing.category or identity.category),
        exit_present=bool(exits.quotes),
        provenance_complete=bool(valuation.provenance),
        source_fresh=age_hours <= 36,
        tax_modelled=True,
        listing_type=listing.listing_type,
        sandbox_source=settings.ebay_api_env == "sandbox" and listing.source_id == "ebay_browse",
    )
    ev = expected_value(
        base_profit=costs.expected_profit_eur,
        upside_profit=costs.upside_profit_eur,
        downside_profit=costs.downside_profit_eur,
        failure_loss=money(-costs.all_in_acquisition_eur * Decimal("0.6")),
    )
    nego = negotiation_targets(
        ask=costs.purchase_price_eur,
        max_buy=costs.max_purchase_eur,
        expected_profit=costs.expected_profit_eur,
        listing_type=listing.listing_type,
    )
    miss = mispricing(
        ask=costs.purchase_price_eur,
        expected=valuation.expected_sale_eur,
        quick=valuation.quick_sale_eur,
        p10=valuation.p10,
    )
    urgency = classify_urgency(
        listing_type=listing.listing_type,
        ends_in_hours=ends_in,
        money_ready=gates.money_ready,
    )
    scenarios = scenario_matrix(
        corridor=corridor,
        customs_value_eur=to_eur(purchase, listing.currency, fx),
        goods_are_second_hand=condition.grade.value not in {"new"},
        vat_rate=_d("vat_rate"),
    )
    val_row = Valuation(
        listing_id=listing.id,
        product_id=listing.product_id,
        method=valuation.method,
        expected_sale_eur=valuation.expected_sale_eur,
        quick_sale_eur=valuation.quick_sale_eur,
        high_eur=valuation.high_eur,
        low_eur=valuation.low_eur,
        confidence=valuation.confidence,
        comparable_count=valuation.comparable_count,
        realised_count=valuation.realised_count,
        local_count=valuation.local_count,
        foreign_count=valuation.foreign_count,
        expected_days_to_sale=valuation.expected_days,
        liquidity_score=liquidity.score,
        provenance=valuation.provenance,
        valued_at=_now(),
    )
    session.add(val_row)
    session.flush()
    for comp in comps:
        session.add(
            Comparable(
                subject_listing_id=listing.id,
                product_id=listing.product_id,
                source_id=comp.source,
                url=comp.url,
                evidence_type=comp.evidence_type.value,
                title=comp.title,
                condition_grade=listing.condition_grade,
                country=comp.country,
                currency="EUR",
                price=comp.price_eur,
                adjusted_price_eur=comp.price_eur,
                observed_at=comp.observed_at,
                product_match_score=comp.product_score,
                condition_match_score=comp.condition_score,
                evidence_weight=comp.product_score,
                outlier=comp.outlier,
                adjustment_notes=comp.notes,
                fingerprint=_fingerprint(comp.source, comp.title, str(comp.price_eur)),
            )
        )
    existing = session.scalar(select(Opportunity).where(Opportunity.listing_id == listing.id))
    payload = dict(
        valuation_id=val_row.id,
        product_id=listing.product_id,
        decision=decision.decision.value,
        engine_decision=decision.decision.value,
        money_ready=gates.money_ready,
        money_ready_decision=gates.money_ready_decision.value,
        expected_value_eur=ev,
        ideal_offer_eur=nego.ideal_offer,
        acceptable_offer_eur=nego.acceptable_offer,
        walk_away_eur=nego.walk_away_price,
        best_exit_channel=exits.best_expected_exit,
        fastest_exit_channel=exits.fastest_exit,
        safest_exit_channel=exits.safest_exit,
        highest_net_exit=exits.highest_net_exit,
        mispricing_score=miss.mispricing_score,
        discount_to_expected=miss.discount_to_expected_sale,
        urgency=urgency.value,
        gate_results={"gates": gates.gates, "failures": gates.failures, "why": gates.why},
        exit_analysis={
            "quotes": [
                {
                    "channel": q.channel,
                    "gross": str(q.gross_expected_sale),
                    "fee": str(q.expected_fee),
                    "payment": str(q.payment_fee),
                    "shipping": str(q.shipping),
                    "returns": str(q.returns_allowance),
                    "days": q.expected_days,
                    "net": str(q.net_proceeds),
                    "confidence": str(q.confidence),
                }
                for q in exits.quotes
            ],
            "best": exits.best_expected_exit,
            "fastest": exits.fastest_exit,
            "safest": exits.safest_exit,
            "highest_net": exits.highest_net_exit,
        },
        negotiation={"ask": str(nego.ask), "ideal": str(nego.ideal_offer), "acceptable": str(nego.acceptable_offer), "walk_away": str(nego.walk_away_price), "notes": nego.notes},
        provenance_pack={
            "identity": {"level": identity.level.value, "confidence": str(identity.confidence), "key": identity.canonical_key, "brand": identity.brand, "model": identity.model, "variant": identity.variant},
            "condition": {"grade": condition.grade.value, "confidence": str(condition.confidence), "notes": condition.notes},
            "valuation": valuation.provenance,
            "tax_scenarios": [{"name": s.name, "import_vat": str(s.estimate.import_vat_eur), "notes": s.estimate.notes} for s in scenarios],
            "shipping": {"inbound": str(inbound.amount_eur), "outbound": str(outbound.amount_eur), "notes": outbound.notes},
            "liquidity": {
                "low": liquidity.expected_days_to_sale_low,
                "expected": liquidity.expected_days_to_sale,
                "high": liquidity.expected_days_to_sale_high,
                "confidence": str(liquidity.liquidity_confidence),
            },
        },
        score=decision.score,
        expected_profit_eur=costs.expected_profit_eur,
        expected_roi=costs.roi,
        margin_percent=money(costs.expected_profit_eur / costs.expected_resale_eur) if costs.expected_resale_eur else ZERO,
        downside_profit_eur=costs.downside_profit_eur,
        upside_profit_eur=costs.upside_profit_eur,
        capital_required_eur=costs.all_in_acquisition_eur,
        max_buy_eur=costs.max_purchase_eur,
        max_hammer_eur=costs.max_hammer_eur,
        all_in_acquisition_eur=costs.all_in_acquisition_eur,
        expected_resale_eur=costs.expected_resale_eur,
        expected_net_resale_eur=costs.expected_net_resale_eur,
        expected_days_to_sale=liquidity.expected_days_to_sale,
        identity_confidence=identity.confidence,
        valuation_confidence=valuation.confidence,
        condition_confidence=condition.confidence,
        why=gates.why + " " + decision.why,
        score_breakdown={
            "profit": str(decision.breakdown.profit),
            "roi": str(decision.breakdown.roi),
            "confidence": str(decision.breakdown.confidence),
            "liquidity": str(decision.breakdown.liquidity),
            "risk_penalty": str(decision.breakdown.risk_penalty),
            "total": str(decision.breakdown.total),
            "notes": decision.breakdown.notes,
        },
        cost_breakdown={
            "lines": [
                {
                    "code": line.code,
                    "label": line.label,
                    "amount_eur": str(line.amount_eur),
                    "assumption_class": line.assumption_class,
                    "notes": line.notes,
                }
                for line in costs.lines
            ],
            "tax_notes": tax.notes,
            "tax_class": tax.assumption_class.value,
            "used_existing_margin_engine": costs.used_existing_margin_engine,
            "best_exit_net": str(best_quote.net_proceeds),
            "inbound_shipping": inbound.notes,
            "outbound_shipping": outbound.notes,
        },
        risks=[{"code": f.code, "severity": f.severity, "detail": f.detail} for f in risk.flags],
        last_evaluated_at=_now(),
    )
    if existing is None:
        existing = Opportunity(listing_id=listing.id, **payload)
        session.add(existing)
    else:
        for key, value in payload.items():
            setattr(existing, key, value)
    session.flush()
    record_observation(session, listing, asking=listing.asking_price)
    open_paper_trade(session, existing)
    record_metric(session, "valuation_count", run_id=str(listing.id))
    if existing.money_ready:
        record_metric(session, "BUY_READY_count", run_id=str(listing.id))
    from app.notifications import notify_opportunity

    notify_opportunity(session, existing)
    return existing


async def run_scan(
    session: Session,
    *,
    source_id: str | None = None,
    query: str | None = None,
    trigger: str = "manual",
    limit: int = 12,
) -> ScanJob:
    seed_sources(session)
    job = ScanJob(
        trigger=trigger,
        source_id=source_id,
        query=query,
        status="running",
        started_at=_now(),
        correlation_id=uuid.uuid4().hex,
        details={},
    )
    session.add(job)
    session.flush()
    seen = 0
    written = 0
    errors: list[str] = []
    try:
        await record_health(session, source_id=source_id if source_id and source_id != "all" else None)
        rates = await refresh_fx(session)
        queries = [query] if query else settings.query_list()[:6]
        adapters = adapter_map()
        targets = [source_id] if source_id and source_id not in {None, "all"} else [
            sid for sid in settings.source_ids() if sid in adapters
        ]
        for sid in targets:
            adapter = adapters.get(sid)
            if adapter is None:
                continue
            if adapter.kind.value not in {"acquisition", "comparable", "manual"}:
                continue
            for q in queries:
                try:
                    items = await adapter.search(q, limit=limit)
                except Exception as exc:
                    logger.warning("search_failed", source=sid, query=q, error=str(exc))
                    errors.append(f"{sid}:{q}:{exc}")
                    continue
                for item in items:
                    seen += 1
                    listing = persist_listing(session, item)
                    comps = await _comps_for(listing, rates, session)
                    evaluate_listing(session, listing, comps, rates)
                    record_metric(session, "records_seen", run_id=job.correlation_id, source=sid)
                    written += 1
        job.status = "partial" if errors else "success"
        job.listings_seen = seen
        job.opportunities_written = written
        job.details = {"errors": errors, "queries": queries, "targets": targets}
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
        logger.exception("scan_failed", error=str(exc))
        raise
    finally:
        job.finished_at = _now()
        session.flush()
    return job
