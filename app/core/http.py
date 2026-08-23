"""Shared HTTP client with retry, timeouts, and rate-limit handling."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("arie.http")


class RateLimitError(RuntimeError):
    """Raised when a source returns HTTP 429."""


class SourceHttpError(RuntimeError):
    """Raised for unexpected HTTP failures after retries."""

    def __init__(self, status_code: int, url: str, body: str) -> None:
        self.status_code = status_code
        self.url = url
        self.body = body
        super().__init__(f"HTTP {status_code} for {url}: {body[:300]}")


def build_client(timeout: float | None = None) -> httpx.AsyncClient:
    """Create an async HTTP client with ARIE defaults."""
    return httpx.AsyncClient(
        timeout=timeout or settings.request_timeout_seconds,
        headers={"User-Agent": settings.http_user_agent, "Accept": "application/json"},
        follow_redirects=True,
    )


@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError, RateLimitError)),
    wait=wait_exponential_jitter(initial=1, max=20),
    stop=stop_after_attempt(4),
    reraise=True,
)
async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    data: dict[str, Any] | str | None = None,
    expected: tuple[int, ...] = (200,),
) -> tuple[httpx.Response, Any]:
    """Perform an HTTP request, retrying timeouts and 429s."""
    response = await client.request(
        method, url, headers=headers, params=params, json=json, data=data
    )
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "1")
        logger.warning("rate_limited", url=url, retry_after=retry_after)
        await asyncio.sleep(min(float(retry_after or 1), 30))
        raise RateLimitError(f"429 for {url}")
    if response.status_code not in expected:
        raise SourceHttpError(response.status_code, url, response.text)
    content_type = response.headers.get("content-type", "")
    payload: Any
    if "json" in content_type or response.text[:1] in "{[":
        payload = response.json()
    else:
        payload = response.text
    return response, payload


SourceHttpError = SourceHttpError
