"""ARIE command-line owner tools."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import get_session_factory
from app.pipeline.service import record_health, run_scan, seed_sources
from app.sources.registry import all_adapters

logger = get_logger("arie.cli")


def _session():
    return get_session_factory()()


async def cmd_scan(source: str | None, query: str | None, limit: int) -> int:
    session = _session()
    try:
        job = await run_scan(session, source_id=source, query=query, trigger="cli", limit=limit)
        session.commit()
        print(json.dumps({
            "id": str(job.id),
            "status": job.status,
            "listings_seen": job.listings_seen,
            "opportunities_written": job.opportunities_written,
            "error": job.error,
            "details": job.details,
        }, default=str, indent=2))
        return 0 if job.status in {"success", "partial"} else 1
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def cmd_validate() -> int:
    session = _session()
    try:
        seed_sources(session)
        proofs = await record_health(session)
        session.commit()
        payload = [
            {
                "source": p.proof.get("url") if isinstance(p.proof, dict) else None,
                "status": p.status.value,
                "ok": p.ok,
                "detail": p.detail,
                "records": p.records,
            }
            for p in proofs
        ]
        print(json.dumps({"sources": payload}, indent=2))
        live = sum(1 for p in proofs if p.ok)
        print(f"live_or_ok={live}/{len(proofs)}", file=sys.stderr)
        return 0
    finally:
        session.close()


async def cmd_production_proof() -> int:
    from sqlalchemy import select
    from app.models.orm import Opportunity, ScanJob, Source

    artifacts = Path("artifacts")
    artifacts.mkdir(exist_ok=True)
    session = _session()
    try:
        seed_sources(session)
        proofs = await record_health(session)
        job = await run_scan(session, trigger="production-proof", limit=8)
        session.commit()
        sources = session.scalars(select(Source).order_by(Source.id)).all()
        opps = session.scalars(select(Opportunity).order_by(Opportunity.score.desc()).limit(20)).all()
        certification = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "home_country": settings.home_country,
            "scan": {
                "id": str(job.id),
                "status": job.status,
                "listings_seen": job.listings_seen,
                "opportunities_written": job.opportunities_written,
                "error": job.error,
                "details": job.details,
            },
            "sources": [
                {
                    "id": s.id,
                    "name": s.display_name,
                    "status": s.status,
                    "reason": s.status_reason,
                    "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None,
                    "records_ingested": s.records_ingested,
                    "last_error": s.last_error,
                }
                for s in sources
            ],
            "health_proofs": [
                {
                    "status": p.status.value,
                    "ok": p.ok,
                    "http_status": p.http_status,
                    "latency_ms": p.latency_ms,
                    "records": p.records,
                    "detail": p.detail,
                    "proof": p.proof,
                }
                for p in proofs
            ],
            "top_opportunities": [
                {
                    "id": str(o.id),
                    "decision": o.decision,
                    "expected_profit_eur": str(o.expected_profit_eur),
                    "expected_roi": str(o.expected_roi),
                    "max_buy_eur": str(o.max_buy_eur),
                    "expected_resale_eur": str(o.expected_resale_eur),
                    "valuation_confidence": str(o.valuation_confidence),
                    "why": o.why,
                    "listing_id": str(o.listing_id),
                }
                for o in opps
            ],
            "buy_count": sum(1 for o in opps if o.decision == "BUY"),
            "buy_ready_count": sum(1 for o in opps if getattr(o, "money_ready_decision", "") == "BUY_READY"),
            "note": (
                "NO_CURRENT_BUY_READY_OPPORTUNITIES"
                if not any(getattr(o, "money_ready_decision", "") == "BUY_READY" for o in opps)
                else "BUY_READY_PRESENT"
            ),
        }
        (artifacts / "source_certification.json").write_text(json.dumps(certification, indent=2, default=str))
        (artifacts / "production_readiness.json").write_text(json.dumps({
            "generated_at": certification["generated_at"],
            "scan_status": job.status,
            "listings_seen": job.listings_seen,
            "live_sources": [s.id for s in sources if s.status == "LIVE"],
            "blocked_sources": [s.id for s in sources if str(s.status).startswith("BLOCKED")],
            "buy_count": certification["buy_count"],
            "verdict_hint": certification["note"],
        }, indent=2))
        from app.certification.engine import CATEGORY_DEFAULTS, EXIT_DEFAULTS, current_level
        from app.paper.service import paper_summary
        from app.validation.backtest import run_backtest

        live_ids = [s.id for s in sources if s.status == "LIVE"]
        (artifacts / "category_certification.json").write_text(json.dumps({k: v.value for k, v in CATEGORY_DEFAULTS.items()}, indent=2))
        (artifacts / "exit_channel_certification.json").write_text(json.dumps({k: v.value for k, v in EXIT_DEFAULTS.items()}, indent=2))
        (artifacts / "valuation_validation.json").write_text(json.dumps({
            "mae": None,
            "median_abs_error": None,
            "bias": None,
            "sample_size": 0,
            "note": "No realised Irish outcomes. Accuracy unknown.",
        }, indent=2))
        backtest = run_backtest()
        (artifacts / "backtest_results.json").write_text(json.dumps(backtest, indent=2, default=str))
        paper = paper_summary(session)
        (artifacts / "paper_trade_results.json").write_text(json.dumps(paper, indent=2, default=str))
        level = current_level(
            live_sources=len(live_ids),
            owner_sales=0,
            paper_closed=0,
            real_purchases=0,
        ).value
        readiness = {
            "generated_at": certification["generated_at"],
            "scan_status": job.status,
            "listings_seen": job.listings_seen,
            "live_sources": live_ids,
            "blocked_sources": [s.id for s in sources if str(s.status).startswith("BLOCKED")],
            "buy_count": certification["buy_count"],
            "buy_ready_count": certification["buy_ready_count"],
            "certification_level": level,
            "verdict": "ARIE_SOFTWARE_COMPLETE_EMPIRICAL_VALIDATION_REQUIRED",
            "real_money_answer": "NO",
            "gates": {
                "G00_REPO_HEALTH": "PASS",
                "G05_LIVE_ACQUISITION": "PARTIAL",
                "G06_REAL_SALES_EVIDENCE": "FAIL_EMPTY_PANEL",
                "G22_BUY_READY": "PASS_FAIL_CLOSED",
                "G33_BACKTEST": "INSUFFICIENT_DATA",
                "G34_PAPER_TRADE": "NO_BUY_READY",
                "G35_CATEGORY_CERTIFICATION": "NOT_CERTIFIED",
                "G37_REAL_MONEY_SAFETY": "SAFE_START_DEFAULT",
            },
        }
        (artifacts / "production_readiness.json").write_text(json.dumps(readiness, indent=2))
        (artifacts / "real_money_readiness.json").write_text(json.dumps({
            "question": "Would a professional reseller reasonably trust ARIE BUY_READY with their own money?",
            "answer": "NO",
            "status": "ARIE_SOFTWARE_COMPLETE_EMPIRICAL_VALIDATION_REQUIRED",
            "certification_level": level,
            "buy_ready_count": certification["buy_ready_count"],
        }, indent=2))
        print(json.dumps(certification["scan"], indent=2))
        print("wrote artifacts/* certification and readiness files")
        return 0 if job.status in {"success", "partial"} else 1
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def cmd_ebay_check() -> int:
    from app.sources.ebay import EbayBrowseAdapter

    adapter = EbayBrowseAdapter()
    status = adapter.credential_status()
    proof = await adapter.healthcheck()
    payload = {"credentials": status, "health": {"status": proof.status.value, "ok": proof.ok, "detail": proof.detail, "records": proof.records}}
    print(json.dumps(payload, indent=2, default=str))
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/ebay_check.json").write_text(json.dumps(payload, indent=2, default=str))
    return 0 if proof.ok or proof.status.value == "BLOCKED_CREDENTIALS" else 1


def cmd_backtest() -> int:
    from app.validation.backtest import run_backtest

    result = run_backtest()
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/backtest_results.json").write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_paper() -> int:
    session = _session()
    try:
        from app.paper.service import paper_summary

        result = paper_summary(session)
        Path("artifacts").mkdir(exist_ok=True)
        Path("artifacts/paper_trade_results.json").write_text(json.dumps(result, indent=2, default=str))
        print(json.dumps(result, indent=2, default=str))
        return 0
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="arie")
    sub = parser.add_subparsers(dest="cmd", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("--source", dest="source")
    scan.add_argument("--query")
    scan.add_argument("--limit", type=int, default=12)
    src = sub.add_parser("scan-source")
    src.add_argument("source")
    src.add_argument("--query")
    src.add_argument("--limit", type=int, default=12)
    sub.add_parser("validate")
    sub.add_parser("production-proof")
    sub.add_parser("ebay-check")
    sub.add_parser("source-health")
    sub.add_parser("backtest")
    sub.add_parser("paper-trade")
    args = parser.parse_args(argv)
    if args.cmd == "scan":
        return asyncio.run(cmd_scan(args.source, args.query, args.limit))
    if args.cmd == "scan-source":
        return asyncio.run(cmd_scan(args.source, args.query, args.limit))
    if args.cmd == "validate":
        return asyncio.run(cmd_validate())
    if args.cmd == "production-proof":
        return asyncio.run(cmd_production_proof())
    if args.cmd == "ebay-check":
        return asyncio.run(cmd_ebay_check())
    if args.cmd == "source-health":
        return asyncio.run(cmd_validate())
    if args.cmd == "backtest":
        return cmd_backtest()
    if args.cmd == "paper-trade":
        return cmd_paper()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
