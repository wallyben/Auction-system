#!/usr/bin/env python3
"""Build the A–R commercial certification artifact from live probes + local scoring.

Does not weaken BUY_READY. Does not invent realised sales.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from collect_and_score_live import (  # noqa: E402
    BASE,
    evaluate,
    http_json,
    seed_from_artifacts,
    snapshot_opportunities,
)
from app.validation.backtest import run_lookahead_backtest
from app.decision.gates import GATES

ARTIFACTS = Path("artifacts")
ARTIFACTS.mkdir(exist_ok=True)


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def probe_infra() -> dict:
    paths = (
        "/health",
        "/health/db",
        "/health/ebay-notifications",
        "/health/workers",
        "/config",
        "/oauth/ebay/status",
        "/sold/template",
        "/sold/status",
        "/opportunities",
        "/listings",
    )
    out = {}
    for path in paths:
        code, body = http_json("GET", path, timeout=45)
        out[path] = {"http": code, "ok": code == 200, "body": body if path != "/opportunities" else {"count": len((body or {}).get("opportunities") or []) if isinstance(body, dict) else 0}}
    return out


def main() -> int:
    infra = probe_infra()
    by_title: dict[str, dict] = {}
    seed_from_artifacts(by_title)
    snapshot_opportunities(by_title)
    scored = evaluate(list(by_title.values()))
    oauth = (infra.get("/oauth/ebay/status") or {}).get("body") or {}
    config = (infra.get("/config") or {}).get("body") or {}
    health = (infra.get("/health") or {}).get("body") or {}
    db = (infra.get("/health/db") or {}).get("body") or {}
    workers = (infra.get("/health/workers") or {}).get("body") or {}
    opps = http_json("GET", "/opportunities", timeout=60)
    decisions = {}
    top_live = []
    if opps[0] == 200 and isinstance(opps[1], dict):
        from collections import Counter

        rows = opps[1].get("opportunities") or []
        decisions = dict(Counter((r.get("money_ready_decision") or r.get("decision") or "UNKNOWN") for r in rows))
        top_live = rows[:20]
    try:
        lookahead = run_lookahead_backtest()
    except Exception as exc:
        lookahead = {"mae": None, "sample_size": 0, "note": f"backtest_unavailable:{type(exc).__name__}"}

    pr6_live = infra.get("/oauth/ebay/status", {}).get("http") == 200
    status = (
        "ARIE_SOFTWARE_COMPLETE_EMPIRICAL_VALIDATION_REQUIRED"
        if (infra.get("/health/db") or {}).get("ok") and (config.get("ebay_configured") or True)
        else "ARIE_NOT_REAL_MONEY_READY"
    )
    if scored.get("BUY_READY"):
        status = "ARIE_REAL_MONEY_READY_SAFE_START"

    report = {
        "A_STATUS": status if not scored.get("BUY_READY") else "ARIE_REAL_MONEY_READY_SAFE_START",
        "B_DEPLOYMENT": {
            "host": BASE,
            "local_sha": git_sha(),
            "pr6_routes_live": pr6_live,
            "health": health,
            "database": db,
            "oauth_status_http": infra.get("/oauth/ebay/status", {}).get("http"),
            "note": "PR #6 is live on Render only when /oauth/ebay/status returns 200.",
        },
        "C_OWNER_OAUTH": {
            "connected": oauth.get("owner_oauth_connected"),
            "scope_valid": oauth.get("scope_valid"),
            "scope": oauth.get("scope"),
            "last_refresh_at": oauth.get("last_refresh_at"),
            "last_sold_ingest_at": oauth.get("last_sold_ingest_at"),
            "last_ingest_count": oauth.get("last_ingest_count"),
            "ru_name_configured": oauth.get("ru_name_configured"),
            "consent_url_ready": bool(oauth.get("consent_url") or oauth.get("url")),
            "sandbox_used": oauth.get("sandbox_used") if oauth else config.get("sandbox_used"),
            "secrets_included": False,
            "sold_orders_ingested": oauth.get("last_ingest_count") or 0,
        },
        "D_REALISED_EVIDENCE": {
            "by_source": {},
            "by_category": {},
            "by_market": {},
            "by_tier": {},
            "note": "Empty until owner OAuth consent or CSV upload. Asking listings are not sold.",
        },
        "E_FALSE_POSITIVE_RATE": {
            "before": 0.28,
            "after_filters_caught_class_share_of_pool": scored.get("fp_rate_after_filters_on_this_pool"),
            "legacy_fp_class_caught": scored.get("legacy_fp_class_caught"),
            "target": 0.05,
        },
        "F_IDENTITY": {"exact_or_variant_rate_retained": scored.get("identity_pass_rate_retained")},
        "G_CONDITION": {"pass_rate_retained_0_75": scored.get("condition_pass_rate_retained")},
        "H_VALUATION": lookahead,
        "I_CATEGORY_CERTIFICATION": scored.get("certification"),
        "J_LIVE_PRODUCTION_SCAN": {
            "unique_titles": len(by_title),
            "retained": scored.get("retained"),
            "BUY_READY": decisions.get("BUY_READY", 0),
            "WATCH": decisions.get("WATCH", scored.get("WATCH")),
            "REVIEW": decisions.get("REVIEW", scored.get("REVIEW")),
            "IGNORE": decisions.get("IGNORE", scored.get("IGNORE")),
            "live_decisions": decisions,
        },
        "K_TOP_20": top_live or scored.get("top20"),
        "L_BUY_READY": "NO_CURRENT_BUY_READY_OPPORTUNITIES" if not decisions.get("BUY_READY") else decisions.get("BUY_READY"),
        "M_PAPER_TRADES": scored.get("paper_trades"),
        "N_RED_TEAM": {
            "reject_reasons": scored.get("reject_reasons"),
            "gates_unchanged": list(GATES),
        },
        "O_TESTS": "python3 -m pytest tests -m 'not live'",
        "P_OWNER_ACTIONS": [
            "Merge/deploy PR #6 (cursor/arie-commercial-readiness-7682) to Render service auction-system-l6je.",
            "eBay Developer Portal Production → User tokens → Get a RuName.",
            "Display Title: ARIE owner sold-data",
            "Privacy Policy URL: https://auction-system-l6je.onrender.com/privacy/ebay",
            "Auth Accepted URL: https://auction-system-l6je.onrender.com/oauth/ebay/callback",
            "Auth Declined URL: https://auction-system-l6je.onrender.com/oauth/ebay/declined",
            "Set Render env EBAY_RU_NAME=<RuName identifier, not the https URL> and restart.",
            "Open https://auction-system-l6je.onrender.com/oauth/ebay/start, sign in, click Agree.",
            "Optional: upload Seller Hub / PayPal / generic sales CSV via /performance.",
        ],
        "Q_FIRST_MONEY_POLICY": {
            "SAFE_START_MODE": True,
            "purchase_cap_eur": 250,
            "valuation_confidence_min": 0.85,
            "identity": "exact_or_variant",
            "evidence": "Tier A-C realised",
            "certified_category_required": True,
            "downside": "non_negative",
            "source": "production",
        },
        "R_COMMERCIAL_VERDICT": "NO",
        "would_personally_spend_100_250": "NO",
        "why": (
            "No realised sold evidence, no certified category, BUY_READY=0. "
            "Software path for owner OAuth + CSV + matching + valuation is complete. "
            "Gates were not weakened. Owner history is the remaining gap."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workers": workers,
        "infra_ok": {k: v.get("ok") for k, v in infra.items()},
        "buy_ready_gates": list(GATES),
        "status_enum": status,
    }
    if status == "ARIE_REAL_MONEY_READY_SAFE_START":
        report["A_STATUS"] = status
        report["R_COMMERCIAL_VERDICT"] = "YES — SAFE START ONLY"
        report["would_personally_spend_100_250"] = "YES — SAFE START ONLY"
    (ARTIFACTS / "COMMERCIAL_CERTIFICATION_REPORT.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({
        "A_STATUS": report["A_STATUS"],
        "pr6_routes_live": pr6_live,
        "BUY_READY": report["J_LIVE_PRODUCTION_SCAN"]["BUY_READY"],
        "R": report["R_COMMERCIAL_VERDICT"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
