"""Adversarial checks on engine output. Never invents a BUY_READY."""

from __future__ import annotations

import re
from typing import Any

from app.sources.ebay_filters import reject_title

_ACCESSORY = re.compile(
    r"\b(case|cover|screen protector|charger|cable|hood|cap|bag|filter|empty box|"
    r"stand|skin|decal|sticker|faceplate|foam pad|power socket|repair part|"
    r"dualsense|manette|boite)\b",
    re.I,
)


def redteam_row(row: dict[str, Any]) -> dict[str, Any]:
    title = row.get("item") or ""
    reasons: list[str] = []
    if _ACCESSORY.search(title) and not _ACCESSORY.search(row.get("query") or ""):
        reasons.append("title_looks_like_accessory")
    filtered = reject_title(row.get("query") or title, title)
    if filtered:
        reasons.append(f"discovery_reject:{filtered}")
    if (row.get("decision") == "BUY_READY") and "PRICE_EVIDENCE_PASS" in (row.get("failed_gates") or []):
        reasons.append("buy_ready_without_price_evidence")
    if row.get("decision") == "BUY_READY" and not row.get("url"):
        reasons.append("buy_ready_missing_url")
    return {
        "id": row.get("id"),
        "item": title[:80],
        "rejected": bool(reasons),
        "reasons": reasons,
        "decision": row.get("decision"),
        "failed_gates": row.get("failed_gates") or [],
    }


def redteam_opportunities(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reviewed = [redteam_row(row) for row in rows]
    return {
        "reviewed": len(reviewed),
        "flagged": sum(1 for row in reviewed if row["rejected"]),
        "buy_ready_flagged": [
            row for row in reviewed if row["decision"] == "BUY_READY" and row["rejected"]
        ],
        "rows": reviewed,
        "note": "Programmatic title/gate inspection. Not a human dealer walkthrough.",
    }
