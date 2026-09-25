"""Next page, numeric page, and bounded scroll. Never click an arbitrary control."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from app.domains.vehicles.browser_market.html_tree import Node
from app.domains.vehicles.browser_market.urls import classify_market_url, is_listing


def next_page_url(html_root: Node, page_url: str) -> str:
    for node in html_root.walk():
        if node.tag == "link" and node.attr("rel").lower() == "next" and node.attr("href"):
            return urljoin(page_url, node.attr("href"))
        if node.tag == "a" and node.attr("rel").lower() == "next" and node.attr("href"):
            return urljoin(page_url, node.attr("href"))
    for node in html_root.walk():
        if node.tag != "a" or not node.attr("href"):
            continue
        label = node.text().strip().lower()
        if label in {"next", "next page", "older", ">"} or label.startswith("next "):
            target = urljoin(page_url, node.attr("href"))
            if not is_listing(classify_market_url(target)):
                return target
    current = _page_number(page_url)
    if current is None:
        return ""
    wanted = str(current + 1)
    for node in html_root.walk():
        if node.tag != "a" or node.text().strip() != wanted or not node.attr("href"):
            continue
        target = urljoin(page_url, node.attr("href"))
        if not is_listing(classify_market_url(target)):
            return target
    return ""


def scroll_should_stop(counts: list[int], *, attempts_without_growth: int = 2, limit: int = 3) -> bool:
    """Stop after two scrolls that add nothing, or when the scroll budget is spent."""

    if len(counts) <= 1:
        return False
    if len(counts) - 1 >= limit:
        return True
    stalled = 0
    for previous, current in zip(counts, counts[1:]):
        stalled = stalled + 1 if current <= previous else 0
        if stalled >= attempts_without_growth:
            return True
    return False


def sequential_page_url(page_url: str) -> str:
    """Carzone-style page query. Used when a cached page has no HTML to read a next link from."""

    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    parsed = urlparse(page_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    current = int(query.get("page") or "1")
    query["page"] = str(current + 1)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _page_number(url: str) -> int | None:
    match = re.search(r"[?&](?:page|p)=(\d+)", url)
    if match:
        return int(match.group(1))
    return 1
