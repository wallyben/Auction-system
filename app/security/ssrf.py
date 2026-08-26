"""URL ingestion allow-list. No arbitrary internal fetches."""

from __future__ import annotations

from urllib.parse import urlparse

ALLOWED_HOSTS = {
    "api.scryfall.com",
    "scryfall.com",
    "api.ebay.com",
    "api.sandbox.ebay.com",
    "www.ebay.ie",
    "www.ebay.co.uk",
    "www.ebay.de",
    "www.ebay.fr",
    "www.ebay.es",
    "www.ebay.it",
    "www.ebay.nl",
    "reverb.com",
    "api.reverb.com",
}


def assert_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http(s) URLs are accepted.")
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        raise ValueError("Local URLs are not allowed.")
    if host.startswith("10.") or host.startswith("192.168.") or host.startswith("172."):
        raise ValueError("Private-network URLs are not allowed.")
    if host not in ALLOWED_HOSTS:
        raise ValueError(
            f"Host {host} is not on the retrieval allow-list. Use owner-assisted capture instead."
        )
    return url
