#!/usr/bin/env python3
"""Live production scan against the Render ARIE host. No sandbox. No fabricated sales."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

BASE = "https://auction-system-l6je.onrender.com"
ARTIFACTS = Path("artifacts")
ARTIFACTS.mkdir(exist_ok=True)

QUERIES = [
    "Sony A7 IV",
    "Sony FE 24-70mm GM II",
    "Sony FE 70-200mm GM II",
    "Canon RF 24-70 f/2.8",
    "Canon RF 50mm f/1.2",
    "MacBook Pro 14 M3",
    "MacBook Pro 16 M3",
    "iPhone 15 Pro 256GB",
    "iPhone 16 Pro 256GB",
    "PlayStation 5",
    "RTX 4070",
    "RTX 4080",
    "Pioneer DDJ-1000",
    "Pioneer DDJ-FLX10",
    "Shure SM7B",
    "Sony A7C II",
]


def http_json(method: str, path: str, body: dict | None = None, timeout: int = 180) -> tuple[int, object]:
    data = None
    headers = {"Accept": "application/json", "User-Agent": "ARIE-production-test/1.0"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {"error": str(exc)}
        except json.JSONDecodeError:
            parsed = {"error": raw[:500]}
        return exc.code, parsed


def http_text(path: str, timeout: int = 60) -> str:
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "ARIE-production-test/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def probe_infra() -> dict:
    out = {}
    for path in (
        "/health",
        "/health/db",
        "/health/ebay-notifications",
        "/health/sources",
        "/health/workers",
        "/config",
    ):
        code, payload = http_json("GET", path, timeout=45)
        out[path] = {"http": code, "body": payload}
    return out


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)


def html_text(html: str) -> str:
    parser = TextExtractor()
    parser.feed(html)
    return "\n".join(parser.parts)


def parse_opportunity_html(html: str, opp_id: str) -> dict:
    text = html_text(html)
    def grab(label: str) -> str | None:
        m = re.search(rf"{re.escape(label)}\n([^\n]+)", text)
        return m.group(1).strip() if m else None

    failed = []
    if "What prevented BUY_READY?" in text:
        block = text.split("What prevented BUY_READY?", 1)[1].split("Why", 1)[0]
        failed = [ln.strip(" -") for ln in block.splitlines() if ln and "All current" not in ln and ln not in {"What prevented BUY_READY?"}]

    url = None
    m = re.search(r'href="(https?://[^"]+)"[^>]*>Open listing', html)
    if m:
        url = m.group(1)

    title = None
    hm = re.search(r"<h1>([^<]+)</h1>", html)
    if hm:
        title = hm.group(1).strip()

    money = None
    mm = re.search(r'class="pill ([A-Z_]+)"', html)
    if mm:
        money = mm.group(1)
    engine = None
    em = re.search(r"engine ([A-Z_]+)", text)
    if em:
        engine = em.group(1)

    return {
        "id": opp_id,
        "item": title,
        "url": url,
        "money_ready_decision": money,
        "engine": engine,
        "ask_raw": grab("Asking / current"),
        "ideal_offer": grab("Ideal offer"),
        "max_buy": grab("MAX SAFE PURCHASE"),
        "expected_sale": grab("Expected sale (range)"),
        "expected_net": grab("Expected net"),
        "expected_profit": grab("Expected profit"),
        "downside": grab("Downside"),
        "roi": grab("ROI"),
        "best_exit": grab("Best exit"),
        "days": grab("Days (band)"),
        "urgency": grab("Urgency"),
        "failed_gates_raw": failed,
        "identity_line": grab("Product identity") or None,
        "why": None,
    }


def accessory_or_mismatch(query: str, title: str) -> str | None:
    q = (query or "").lower()
    t = (title or "").lower()
    accessory = (
        "case", "cover", "screen protector", "charger", "cable", "empty box", "box only",
        "parts only", "for parts", "hood only", "lens cap", "body cap", "bag only",
        "laptop gpu", "mobile gpu", "replica", "not genuine", "broken", "cracked lcd",
        "housing only", "dummy", "display model",
    )
    for word in accessory:
        if word in t and word not in q:
            return f"accessory_or_damaged:{word}"
    if "a7 iv" in q or "a7iv" in q.replace(" ", ""):
        if re.search(r"a7r\s*iv|a7s\s*iv|a7c\s*iv|a7 iii|a7iii|a7r iii", t) and "a7 iv" not in t and "a7iv" not in t.replace(" ", "") and "ilce-7m4" not in t:
            return "wrong_generation_a7"
        if "a7r" in t and "a7 iv" in q:
            if "a7riv" in t.replace(" ", "") or "a7r iv" in t or "ilce-7rm4" in t:
                return "wrong_generation_a7r"
    if "kit" in t or "bundle" in t or "lot of" in t:
        if "kit" not in q and "bundle" not in q:
            return "bundle_or_kit"
    if "4070" in q and re.search(r"laptop|mobile|max-q", t):
        return "laptop_gpu"
    if "4080" in q and re.search(r"laptop|mobile|max-q", t):
        return "laptop_gpu"
    if "macbook" in q and re.search(r"case|cover|charger|sleeve", t):
        return "macbook_accessory"
    if "iphone" in q and re.search(r"case|cover|screen|charger|cable|box only", t):
        return "iphone_accessory"
    if ("playstation 5" in q or "ps5" in q) and "digital" in t and "digital" not in q:
        return "ps5_digital"
    return None


def money_to_float(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = re.sub(r"[^0-9.,-]", "", value).replace(",", "")
    if cleaned in {"", "-", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()
    infra_before = probe_infra()
    (ARTIFACTS / "live_infra_before.json").write_text(json.dumps(infra_before, indent=2, default=str))

    ebay = next(
        (s for s in infra_before["/health/sources"]["body"].get("sources", []) if s["id"] == "ebay_browse"),
        {},
    )
    sandbox = False
    scan_results = []
    total_seen = 0
    total_written = 0

    queries_to_run = QUERIES
    for query in queries_to_run:
        print(f"SCAN {query}", flush=True)
        t0 = time.time()
        code, payload = http_json(
            "POST",
            "/scans",
            {"source_id": "ebay_browse", "query": query, "limit": 20},
            timeout=180,
        )
        elapsed = round(time.time() - t0, 1)
        row = {
            "query": query,
            "http": code,
            "elapsed_s": elapsed,
            "payload": payload,
        }
        scan_results.append(row)
        if isinstance(payload, dict):
            total_seen += int(payload.get("listings_seen") or 0)
            total_written += int(payload.get("opportunities_written") or 0)
        print(f"  http={code} seen={payload.get('listings_seen') if isinstance(payload, dict) else '?'} {elapsed}s", flush=True)
        time.sleep(0.8)

    infra_after = probe_infra()
    code, scans = http_json("GET", "/scans", timeout=45)
    code, opps = http_json("GET", "/opportunities", timeout=60)
    opportunities = opps.get("opportunities") if isinstance(opps, dict) else []

    details = []
    false_positives = []
    for opp in opportunities:
        oid = opp.get("id")
        title = opp.get("title") or ""
        fp = accessory_or_mismatch("", title)
        parsed = {"id": oid, **opp, "discovery_flag": fp}
        try:
            html = http_text(f"/opportunities/{oid}/view", timeout=45)
            parsed.update(parse_opportunity_html(html, oid))
        except Exception as exc:  # noqa: BLE001
            parsed["html_error"] = type(exc).__name__
        if fp:
            false_positives.append({"id": oid, "title": title, "reason": fp, "url": opp.get("url")})
        details.append(parsed)
        time.sleep(0.15)

    # Second-pass discovery using query hints from scans is approximate; title-only here.
    decisions = Counter(d.get("money_ready_decision") or d.get("decision") for d in details)
    engine = Counter(d.get("engine") for d in details)

    ranked = sorted(
        details,
        key=lambda d: (
            0 if (d.get("money_ready_decision") == "BUY_READY" or d.get("decision") == "BUY") else 1,
            -(money_to_float(str(d.get("expected_profit_eur") or d.get("expected_profit") or "0")) or -9999),
            -(money_to_float(str(d.get("expected_roi") or "0")) or 0),
        ),
    )

    top20 = []
    redteam = []
    for row in ranked[:40]:
        title = row.get("item") or row.get("title") or ""
        reasons = []
        flag = accessory_or_mismatch("", title)
        if flag:
            reasons.append(flag)
        if "sandbox.ebay" in (row.get("url") or ""):
            reasons.append("sandbox_url")
            sandbox = True
        failed = row.get("failed_gates_raw") or []
        failed_names = []
        for item in failed:
            name = item.split("—")[0].split("-")[0].strip()
            if name:
                failed_names.append(name)
        audit = {
            "id": row.get("id"),
            "item": title[:140],
            "source_country": row.get("country"),
            "url": row.get("url"),
            "ask": row.get("asking_price") or row.get("ask_raw"),
            "ideal_offer": row.get("ideal_offer"),
            "max_buy": row.get("max_buy") or row.get("max_buy_eur"),
            "expected_sale": row.get("expected_sale") or row.get("expected_resale_eur"),
            "expected_profit": row.get("expected_profit") or row.get("expected_profit_eur"),
            "roi": row.get("roi") or row.get("expected_roi"),
            "confidence": row.get("valuation_confidence"),
            "best_exit": row.get("best_exit") or row.get("best_exit_channel"),
            "failed_gates": failed_names or failed,
            "decision": row.get("money_ready_decision") or row.get("decision"),
            "engine": row.get("engine"),
            "identity_confidence": row.get("identity_confidence"),
            "days": row.get("expected_days_to_sale") or row.get("days"),
            "redteam_reasons": reasons,
            "rejected": bool(reasons),
        }
        redteam.append(audit)
        if not audit["rejected"] and len(top20) < 20:
            top20.append(audit)

    paper = []
    for row in top20:
        decision = row.get("decision")
        engine_d = row.get("engine")
        interesting = decision in {"BUY_READY", "WATCH"} or engine_d == "BUY"
        profit = money_to_float(str(row.get("expected_profit") or "0")) or 0
        if decision == "REVIEW" and profit > 40:
            interesting = True
        if not interesting:
            continue
        paper.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "item": row.get("item"),
            "url": row.get("url"),
            "ask": row.get("ask"),
            "max_buy": row.get("max_buy"),
            "predicted_resale": row.get("expected_sale"),
            "expected_profit": row.get("expected_profit"),
            "expected_days": row.get("days"),
            "failed_gates": row.get("failed_gates"),
            "decision": decision,
            "engine": engine_d,
            "status": "open",
            "note": "Paper only. Listing disappearance is not a sale.",
        })

    buy_ready = [r for r in details if (r.get("money_ready_decision") or r.get("decision")) == "BUY_READY"]
    buy_ready_audit = []
    for row in buy_ready:
        fails = []
        url = row.get("url") or ""
        if "sandbox" in url:
            fails.append("not_production_source")
        if accessory_or_mismatch("", row.get("item") or row.get("title") or ""):
            fails.append("identity_or_accessory")
        failed = " ".join(row.get("failed_gates_raw") or [])
        if "PRICE_EVIDENCE_PASS" in failed:
            fails.append("price_evidence_failed")
        if "CATEGORY_CERT_PASS" in failed:
            fails.append("uncertified_category")
        buy_ready_audit.append({"id": row.get("id"), "item": row.get("item") or row.get("title"), "fails": fails, "keep": not fails})

    gate_counter: Counter[str] = Counter()
    for row in details:
        for g in row.get("failed_gates_raw") or []:
            name = g.split("—")[0].split("-")[0].strip()
            if name:
                gate_counter[name] += 1

    ebay_after = next(
        (s for s in infra_after["/health/sources"]["body"].get("sources", []) if s["id"] == "ebay_browse"),
        {},
    )

    report = {
        "generated_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "host": BASE,
        "A_infrastructure": {
            "health": infra_after["/health"],
            "db": infra_after["/health/db"],
            "ebay_notifications": {
                k: infra_after["/health/ebay-notifications"]["body"].get(k)
                for k in (
                    "ready",
                    "ready_for_ebay_challenge",
                    "endpoint_configured",
                    "endpoint_https",
                    "verification_token_configured",
                    "database",
                    "ebay_subscription_active",
                )
            },
            "workers": infra_after["/health/workers"],
        },
        "B_live_source": {
            "ebay_status": ebay_after.get("status"),
            "ebay_reason": ebay_after.get("reason"),
            "last_success_at": ebay_after.get("last_success_at"),
            "ebay_configured": infra_after["/config"]["body"].get("ebay_configured"),
            "sandbox_used": sandbox,
            "enabled_sources": infra_after["/config"]["body"].get("enabled_sources"),
            "market_note": "Render ebay_browse healthcheck uses production hosts when keyset is PRD.",
        },
        "C_scan_size": {
            "queries": queries_to_run,
            "scan_jobs": scan_results,
            "listings_seen_sum": total_seen,
            "opportunities_written_sum": total_written,
            "opportunities_returned": len(opportunities),
            "scan_log": scans,
        },
        "D_top_20": top20,
        "E_buy_ready": {
            "count": len(buy_ready),
            "rows": buy_ready_audit,
        },
        "F_paper_trades": paper,
        "G_false_positives": false_positives,
        "H_redteam": redteam,
        "I_failed_gates": gate_counter.most_common(),
        "metrics": {
            "listings_scanned": total_seen,
            "listings_retained": total_written,
            "false_positive_count": len(false_positives),
            "opportunities_produced": len(details),
            "BUY_READY": decisions.get("BUY_READY", 0),
            "WATCH": decisions.get("WATCH", 0),
            "REVIEW": decisions.get("REVIEW", 0),
            "IGNORE": decisions.get("IGNORE", 0),
            "engine": dict(engine),
            "decisions": dict(decisions),
        },
        "ebay_before": ebay,
    }
    (ARTIFACTS / "live_production_test.json").write_text(json.dumps(report, indent=2, default=str))
    (ARTIFACTS / "current_opportunity_scan.json").write_text(json.dumps({
        "generated_at": report["finished_at"],
        "listings_scanned": total_seen,
        "opportunities_evaluated": total_written,
        "decisions": dict(decisions),
        "buy_ready": decisions.get("BUY_READY", 0),
        "top_20": top20,
        "redteam": {"reviewed": len(redteam), "flagged": sum(1 for r in redteam if r["rejected"]), "rows": redteam},
    }, indent=2, default=str))
    (ARTIFACTS / "paper_trade_results.json").write_text(json.dumps({
        "count": len(paper),
        "open": len(paper),
        "note": "No fabricated dispositions. Open trades remain open until evidence exists.",
        "trades": paper,
    }, indent=2, default=str))
    print(json.dumps({
        "listings_seen": total_seen,
        "written": total_written,
        "opps": len(details),
        "buy_ready": decisions.get("BUY_READY", 0),
        "false_positives": len(false_positives),
        "top20": len(top20),
        "paper": len(paper),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
