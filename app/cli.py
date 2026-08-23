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
            "note": "NO_CURRENT_OPPORTUNITY_PASSED_THRESHOLDS" if not any(o.decision == "BUY" for o in opps) else "BUY_CANDIDATES_PRESENT",
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
        print(json.dumps(certification["scan"], indent=2))
        print("wrote artifacts/source_certification.json")
        return 0 if job.status in {"success", "partial"} else 1
    except Exception:
        session.rollback()
        raise
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
    args = parser.parse_args(argv)
    if args.cmd == "scan":
        return asyncio.run(cmd_scan(args.source, args.query, args.limit))
    if args.cmd == "scan-source":
        return asyncio.run(cmd_scan(args.source, args.query, args.limit))
    if args.cmd == "validate":
        return asyncio.run(cmd_validate())
    if args.cmd == "production-proof":
        return asyncio.run(cmd_production_proof())
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
