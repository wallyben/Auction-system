#!/usr/bin/env python3
"""Second-pass red-team of the live Render scan. Does not weaken BUY_READY gates."""

from __future__ import annotations

import json
import re
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from app.sources.ebay_filters import reject_title

BASE = "https://auction-system-l6je.onrender.com"
ARTIFACTS = Path("artifacts")

QUERY_HINTS = (
    (re.compile(r"ddj[-\s]?flx10", re.I), "Pioneer DDJ-FLX10"),
    (re.compile(r"ddj[-\s]?1000", re.I), "Pioneer DDJ-1000"),
    (re.compile(r"sm7b", re.I), "Shure SM7B"),
    (re.compile(r"24-70.*gm|gm.*24-70|sel2470gm2", re.I), "Sony FE 24-70mm GM II"),
    (re.compile(r"70-200.*gm|sel70200gm2", re.I), "Sony FE 70-200mm GM II"),
    (re.compile(r"rf\s*24-70", re.I), "Canon RF 24-70 f/2.8"),
    (re.compile(r"rf\s*50", re.I), "Canon RF 50mm f/1.2"),
    (re.compile(r"a7\s*iv|a7iv|ilce-7m4", re.I), "Sony A7 IV"),
    (re.compile(r"a7c\s*ii|a7c2", re.I), "Sony A7C II"),
    (re.compile(r"macbook", re.I), "MacBook Pro 14 M3"),
    (re.compile(r"iphone\s*16", re.I), "iPhone 16 Pro 256GB"),
    (re.compile(r"iphone\s*15", re.I), "iPhone 15 Pro 256GB"),
    (re.compile(r"iphone\s*14", re.I), "iPhone 15 Pro 256GB"),
    (re.compile(r"rtx\s*4080", re.I), "RTX 4080"),
    (re.compile(r"rtx\s*4070", re.I), "RTX 4070"),
    (re.compile(r"playstation|ps5", re.I), "PlayStation 5"),
)


def infer_query(title: str) -> str:
    for pattern, query in QUERY_HINTS:
        if pattern.search(title or ""):
            return query
    return title or ""


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


def http_json(path: str):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "ARIE-redteam/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def http_text(path: str) -> str:
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "ARIE-redteam/1.0"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", errors="replace")


def grab(text: str, label: str) -> str | None:
    m = re.search(rf"{re.escape(label)}\n([^\n]+)", text)
    return m.group(1).strip() if m else None


def parse_html(html: str) -> dict:
    text = html_text(html)
    failed = []
    if "What prevented BUY_READY?" in text:
        block = text.split("What prevented BUY_READY?", 1)[1].split("Why", 1)[0]
        failed = [ln.strip(" -") for ln in block.splitlines() if ln and "All current" not in ln]
    url = None
    m = re.search(r'href="(https?://[^"]+)"', html)
    if m:
        url = m.group(1).replace("&amp;", "&")
    money = None
    mm = re.search(r'class="pill ([A-Z_]+)"', html)
    if mm:
        money = mm.group(1)
    identity_conf = None
    im = re.search(r"identity (\d+)%", text)
    if im:
        identity_conf = int(im.group(1)) / 100
    val_conf = None
    vm = re.search(r"valuation (\d+)%", text)
    if vm:
        val_conf = int(vm.group(1)) / 100
    cond_conf = None
    cm = re.search(r"condition (\d+)%", text)
    if cm:
        cond_conf = int(cm.group(1)) / 100
    return {
        "ask_display": grab(text, "Asking / current"),
        "ideal_offer": grab(text, "Ideal offer"),
        "max_buy": grab(text, "MAX SAFE PURCHASE"),
        "expected_sale": grab(text, "Expected sale (range)"),
        "quick_sale_note": "quick-sale is the valuation quick_sale_eur; HTML shows expected sale range",
        "expected_net": grab(text, "Expected net"),
        "expected_profit": grab(text, "Expected profit"),
        "downside": grab(text, "Downside"),
        "roi": grab(text, "ROI"),
        "best_exit": grab(text, "Best exit"),
        "days": grab(text, "Days (band)"),
        "failed_gates": failed,
        "money_ready_decision": money,
        "open_url": url,
        "identity_conf": identity_conf,
        "valuation_conf": val_conf,
        "condition_conf": cond_conf,
        "why": grab(text, "Why"),
    }


def extra_redteam(title: str, country: str, ask: float | None) -> list[str]:
    reasons = []
    t = (title or "").lower()
    if ask is not None:
        if "sm7b" in t and ask < 150:
            reasons.append("counterfeit_risk_sm7b_below_street")
        if "flx10" in t and ask < 700:
            reasons.append("implausible_flx10_price")
        if "ddj-1000" in t or "ddj1000" in t:
            if ask < 500:
                reasons.append("implausible_ddj1000_price")
        if "a7 iv" in t or "a7iv" in t or "ilce-7m4" in t:
            if ask < 700:
                reasons.append("implausible_a7iv_price")
    if country in {"CN", "HK"} and ask and ask < 100:
        reasons.append("cn_low_price_accessory_risk")
    if "please read" in t or "text me before buying" in t:
        reasons.append("seller_warning_in_title")
    if "shutter" in t:
        m = re.search(r"(\d[\d\s]{2,})\s*(ausl|ottur|shutter|sc\b)", t)
        if m:
            n = int(re.sub(r"\D", "", m.group(1)) or "0")
            if n > 100000:
                reasons.append("high_shutter_count")
    if re.search(r"\+\s*(monitor|fortnite|fifa|hp 22)", t):
        reasons.append("bundle_with_unrelated_goods")
    return reasons


def money_float(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = re.sub(r"[^0-9.,-]", "", str(value)).replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def main() -> int:
    opps = json.loads(Path("artifacts/live_opportunities_api.json").read_text())
    classified = []
    fps = []
    genuine = []
    identity_exactish = 0
    variant_amb = 0
    for row in opps:
        title = row.get("title") or ""
        query = infer_query(title)
        reason = reject_title(query, title)
        ask = money_float(row.get("asking_price"))
        extra = extra_redteam(title, row.get("country") or "", ask)
        rejected = bool(reason) or bool(extra and any(
            x.startswith(("counterfeit", "implausible", "bundle_with")) for x in extra
        ))
        rec = {
            **row,
            "inferred_query": query,
            "discovery_reject": reason,
            "extra_redteam": extra,
            "rejected": rejected,
        }
        classified.append(rec)
        if reason:
            fps.append({"title": title, "reason": reason, "url": row.get("url"), "country": row.get("country"), "ask": row.get("asking_price")})
        elif not rejected:
            genuine.append(rec)
        conf = money_float(row.get("identity_confidence")) or 0
        if conf >= 0.90:
            identity_exactish += 1
        elif 0.55 <= conf < 0.90:
            variant_amb += 1

    # Rank genuine by dealer-usefulness: closer ask to expected, then less-negative profit, prefer EU/GB/IE
    def rank_key(r):
        profit = money_float(r.get("expected_profit_eur")) or -9999
        conf = money_float(r.get("valuation_confidence")) or 0
        ask = money_float(r.get("asking_price")) or 0
        eu = 0 if r.get("country") in {"IE", "GB", "DE", "FR", "IT", "ES", "NL"} else 1
        # Prefer items with some valuation signal, then least-bad economics, EU first
        return (0 if conf >= 0.15 else 1, eu, -profit, ask)

    genuine_sorted = sorted(genuine, key=rank_key)
    top_candidates = genuine_sorted[:20]
    details = []
    for row in top_candidates:
        oid = row["id"]
        try:
            html = http_text(f"/opportunities/{oid}/view")
            parsed = parse_html(html)
        except Exception as exc:  # noqa: BLE001
            parsed = {"html_error": type(exc).__name__}
        details.append({
            "item": row.get("title"),
            "source_country": row.get("country"),
            "live_url": (parsed.get("open_url") or row.get("url") or "").replace("&amp;", "&"),
            "ask": parsed.get("ask_display") or f"{row.get('currency')} {row.get('asking_price')}",
            "ideal_offer": parsed.get("ideal_offer"),
            "max_buy": parsed.get("max_buy") or f"€{row.get('max_buy_eur')}",
            "quick_sale_estimate": parsed.get("expected_sale"),
            "expected_sale": parsed.get("expected_sale") or f"€{row.get('expected_resale_eur')}",
            "expected_profit": parsed.get("expected_profit") or f"€{row.get('expected_profit_eur')}",
            "roi": parsed.get("roi") or row.get("expected_roi"),
            "confidence": parsed.get("valuation_conf") if parsed.get("valuation_conf") is not None else row.get("valuation_confidence"),
            "identity_confidence": parsed.get("identity_conf") if parsed.get("identity_conf") is not None else row.get("identity_confidence"),
            "best_exit": parsed.get("best_exit") or row.get("best_exit_channel"),
            "failed_gates": parsed.get("failed_gates") or row.get("failed_gates") or [],
            "decision": parsed.get("money_ready_decision") or row.get("money_ready_decision") or row.get("decision"),
            "extra_redteam": row.get("extra_redteam"),
            "id": oid,
        })
        time.sleep(0.12)

    paper = []
    for d in details:
        profit = money_float(str(d.get("expected_profit"))) or 0
        conf = float(d.get("confidence") or 0)
        interesting = conf >= 0.15 or profit > -400
        if not interesting:
            continue
        paper.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "item": d["item"],
            "url": d["live_url"],
            "ask": d["ask"],
            "max_buy": d["max_buy"],
            "predicted_resale": d["expected_sale"],
            "expected_profit": d["expected_profit"],
            "expected_days": 45,
            "failed_gates": d["failed_gates"],
            "decision": d["decision"],
            "status": "open",
            "note": "Paper only. Listing disappearance is not a sale. No BUY_READY.",
        })

    reason_counts = Counter(x["reason"] for x in fps)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "listings_in_api_window": len(opps),
        "false_positives_in_window": len(fps),
        "false_positive_rate_window": round(len(fps) / max(len(opps), 1), 3),
        "genuine_retained": len(genuine),
        "identity_high_rate": round(identity_exactish / max(len(opps), 1), 3),
        "variant_ambiguity_rate": round(variant_amb / max(len(opps), 1), 3),
        "fp_reasons": reason_counts.most_common(),
        "false_positives": fps,
        "top_20_genuine": details,
        "paper_trades": paper,
        "buy_ready": 0,
        "note": (
            "API returns top 100 by engine score. 224 listings were written. "
            "This second pass re-ranks after rejecting accessories/wrong variants. "
            "BUY_READY remains 0. PRICE_EVIDENCE_PASS was not lowered."
        ),
    }
    (ARTIFACTS / "live_redteam_rerank.json").write_text(json.dumps(report, indent=2, default=str))
    (ARTIFACTS / "paper_trade_results.json").write_text(json.dumps({
        "count": len(paper),
        "open": len(paper),
        "note": "No fabricated dispositions. Open trades remain open until evidence exists.",
        "trades": paper,
    }, indent=2, default=str))
    print(json.dumps({
        "window": len(opps),
        "fps": len(fps),
        "fp_rate": report["false_positive_rate_window"],
        "genuine": len(genuine),
        "top20": len(details),
        "paper": len(paper),
        "fp_reasons": reason_counts.most_common(),
    }, indent=2))
    for i, d in enumerate(details, 1):
        print(f"{i:2}. {d['source_country']} {d['ask']} profit={d['expected_profit']} conf={d['confidence']} | {d['item'][:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
