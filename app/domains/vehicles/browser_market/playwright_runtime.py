"""One Chromium process per harvest. No stealth, no persisted marketplace login."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from app.domains.vehicles.browser_market.base import PageFetch
from app.domains.vehicles.browser_market.challenge import detect_challenge, retryable

_GLOBAL = threading.BoundedSemaphore(2)
_HOSTS: dict[str, threading.Lock] = {}
_HOST_GUARD = threading.Lock()


def host_lock(host: str) -> threading.Lock:
    key = host.lower().removeprefix("www.")
    with _HOST_GUARD:
        lock = _HOSTS.get(key)
        if lock is None:
            lock = threading.Lock()
            _HOSTS[key] = lock
        return lock


class BrowserSession:
    """Reusable browser for one harvest job. Pages and the process always close."""

    def __init__(self, *, timeout_ms: int = 30000) -> None:
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None
        self._context = None
        self.closed = False

    def open(self) -> None:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            locale="en-IE",
            timezone_id="Europe/Dublin",
            viewport={"width": 1366, "height": 900},
            java_script_enabled=True,
            accept_downloads=False,
        )
        self._context.route("**/*", self._route)

    def _route(self, route) -> None:
        if route.request.resource_type in {"image", "media", "font"}:
            route.abort()
            return
        route.continue_()

    def fetch(self, url: str) -> PageFetch:
        if self._context is None:
            self.open()
        page = self._context.new_page()
        page.set_default_navigation_timeout(self.timeout_ms)
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=min(self.timeout_ms, 8000))
            except Exception:
                pass
            status = response.status if response is not None else 0
            html = page.content()
            final = page.url
            challenge = detect_challenge(status, html, final)
            return PageFetch(url=url, final_url=final, status_code=status, html="" if challenge else html, challenge=challenge)
        except Exception as exc:
            message = str(exc)
            challenge = "NAVIGATION_FAILED"
            if "Timeout" in message or "timeout" in message:
                challenge = "NAVIGATION_FAILED"
            return PageFetch(url=url, final_url=url, status_code=0, html="", challenge=challenge, error=message[:300])
        finally:
            try:
                page.close()
            except Exception:
                pass

    def scroll_once(self, url: str) -> PageFetch:
        if self._context is None:
            self.open()
        page = self._context.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(800)
            status = response.status if response is not None else 0
            html = page.content()
            challenge = detect_challenge(status, html, page.url)
            return PageFetch(url=url, final_url=page.url, status_code=status, html="" if challenge else html, challenge=challenge)
        except Exception as exc:
            return PageFetch(url=url, final_url=url, status_code=0, html="", challenge="NAVIGATION_FAILED", error=str(exc)[:300])
        finally:
            try:
                page.close()
            except Exception:
                pass

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for item in (self._context, self._browser):
            if item is None:
                continue
            try:
                item.close()
            except Exception:
                pass
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._context = None
        self._browser = None
        self._playwright = None


@contextmanager
def browser_session(*, timeout_ms: int = 30000) -> Iterator[BrowserSession]:
    _GLOBAL.acquire()
    session = BrowserSession(timeout_ms=timeout_ms)
    try:
        yield session
    finally:
        session.close()
        _GLOBAL.release()


def fetch_with_retry(session: BrowserSession, url: str, *, attempts: int = 2) -> PageFetch:
    last = PageFetch(url=url, final_url=url, status_code=0, html="", challenge="NAVIGATION_FAILED")
    for _ in range(attempts):
        last = session.fetch(url)
        if not retryable(last.challenge, last.status_code):
            return last
        if last.challenge == "" and last.status_code < 500:
            return last
    return last
