"""Web-process request telemetry, event-loop lag, and bounded memory samples.

No secrets: no query strings, bodies, cookies, Authorization, or signatures.
"""

from __future__ import annotations

import asyncio
import gc
import hashlib
import os
import sys
import threading
import time
import uuid
from collections import deque
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.logging import get_logger
from app.core.runtime import process_runtime_snapshot, rss_mb, thread_count

logger = get_logger("arie.web.observability")

RING_MAX = 200
SAMPLE_MAX = 72
STALL_WARN_S = 2.0
STALL_DUMP_S = 5.0
PULSE_S = 0.25
WATCHDOG_S = 0.5
SAMPLE_S = 5.0

_FORBIDDEN_HEADER = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-ebay-signature",
    "x-api-key",
}

_ring: deque[dict[str, Any]] = deque(maxlen=RING_MAX)
_samples: deque[dict[str, Any]] = deque(maxlen=SAMPLE_MAX)
_stalls: deque[dict[str, Any]] = deque(maxlen=32)
_in_flight = 0
_in_flight_lock = threading.Lock()
_pulse_mono = time.monotonic()
_lag_s = 0.0
_stop = threading.Event()
_watchdog_thread: threading.Thread | None = None
_sample_thread: threading.Thread | None = None
_pulse_task: asyncio.Task[None] | None = None
_last_dump_mono = 0.0
_started_mono = time.monotonic()
_stall_episode = False

_SECRET_FIELD = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-ebay-signature",
    "x-api-key",
    "code",
    "challenge_code",
    "challengecode",
    "signature",
    "token",
    "refresh_token",
    "access_token",
    "query",
    "query_string",
    "body",
}


def _ua_family(ua: str) -> str:
    low = (ua or "").lower()
    if "render" in low or "health-check" in low:
        return "render-health"
    if "ebay" in low:
        return "ebay"
    if "arie-" in low:
        return "arie-probe"
    if "python-urllib" in low or "python-requests" in low or "httpx" in low:
        return "script"
    if "curl" in low:
        return "curl"
    if "mozilla" in low or "chrome" in low or "safari" in low:
        return "browser"
    return "unknown"


def _client_class(path: str, ua: str) -> str:
    if path.startswith("/webhooks/ebay"):
        return "ebay"
    family = _ua_family(ua)
    if family == "render-health":
        return "render-health"
    if family in {"arie-probe", "script", "curl", "browser"}:
        return family
    return "unknown"


def _ua_hash(ua: str) -> str:
    if not ua:
        return ""
    return hashlib.blake2s(ua.encode("utf-8", "replace"), digest_size=6).hexdigest()


def fd_count() -> int | None:
    try:
        return len(os.listdir("/proc/self/fd"))
    except Exception:
        return None


def python_alloc_mb() -> float | None:
    try:
        import tracemalloc

        if tracemalloc.is_tracing():
            current, _peak = tracemalloc.get_traced_memory()
            return round(current / (1024 * 1024), 2)
    except Exception:
        pass
    try:
        import resource

        # ru_maxrss is high-water, not current Python heap. Keep as fallback only.
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if rss > 10_000_000:
            return None
        return None
    except Exception:
        return None


def sqlalchemy_pool_snapshot() -> dict[str, Any]:
    """Cheap pool stats. Never opens a connection."""
    try:
        from app.db import session as db_session

        engine = db_session._engine
        if engine is None:
            return {"configured": False}
        pool = engine.pool
        out: dict[str, Any] = {"configured": True, "pool_class": type(pool).__name__}
        for name in ("checkedout", "checkedin", "size", "overflow"):
            fn = getattr(pool, name, None)
            if callable(fn):
                try:
                    out[name] = int(fn())
                except Exception:
                    out[name] = None
        return out
    except Exception:
        return {"configured": False}


def _public_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k.lower() not in _SECRET_FIELD and k.lower() not in _FORBIDDEN_HEADER}


def memory_sample() -> dict[str, Any]:
    counts = gc.get_count()
    with _in_flight_lock:
        inflight = _in_flight
    objects_n = None
    try:
        objects_n = len(gc.get_objects())
    except Exception:
        objects_n = None
    return {
        "ts": time.time(),
        "rss_mb": rss_mb(),
        "gc_counts": list(counts),
        "gc_objects": objects_n,
        "threads": thread_count(),
        "fds": fd_count(),
        "in_flight": inflight,
        "ring_n": len(_ring),
        "loop_lag_s": round(_lag_s, 3),
        "python_alloc_mb": python_alloc_mb(),
        "pool": sqlalchemy_pool_snapshot(),
    }


def _record_request(entry: dict[str, Any]) -> None:
    _ring.append(entry)


def recent_requests(*, limit: int = 50) -> list[dict[str, Any]]:
    items = list(_ring)
    return items[-max(1, min(limit, RING_MAX)) :]


def recent_samples(*, limit: int = 72) -> list[dict[str, Any]]:
    items = list(_samples)
    return items[-max(1, min(limit, SAMPLE_MAX)) :]


def recent_stalls(*, limit: int = 16) -> list[dict[str, Any]]:
    items = list(_stalls)
    return items[-max(1, min(limit, 32)) :]


def in_flight_count() -> int:
    with _in_flight_lock:
        return _in_flight


def loop_lag_s() -> float:
    return round(_lag_s, 3)


def diagnostic_snapshot() -> dict[str, Any]:
    runtime = process_runtime_snapshot()
    return {
        "runtime": runtime,
        "loop_lag_s": loop_lag_s(),
        "in_flight": in_flight_count(),
        "ring_n": len(_ring),
        "sample_n": len(_samples),
        "pool": sqlalchemy_pool_snapshot(),
        "uptime_s": int(time.monotonic() - _started_mono),
        "last_requests": recent_requests(limit=40),
        "memory_samples": recent_samples(limit=24),
        "stalls": recent_stalls(limit=8),
        "secrets_included": False,
    }


def _stack_summaries(*, limit_frames: int = 30) -> list[dict[str, Any]]:
    """Filename/line/function only. Never dump f_locals (tokens live there)."""
    out: list[dict[str, Any]] = []
    try:
        frames = sys._current_frames()
    except Exception:
        return out
    for thread_id, frame in frames.items():
        stack: list[str] = []
        cur = frame
        depth = 0
        while cur is not None and depth < limit_frames:
            code = cur.f_code
            stack.append(f"{code.co_filename}:{cur.f_lineno}:{code.co_name}")
            cur = cur.f_back
            depth += 1
        out.append({"thread_id": int(thread_id), "stack": stack})
    return out


def _note_stall(lag: float, *, dump: bool) -> None:
    sample = memory_sample()
    payload: dict[str, Any] = {
        "lag_seconds": round(lag, 3),
        "pid": os.getpid(),
        "rss_mb": sample.get("rss_mb"),
        "threads": sample.get("threads"),
        "in_flight": sample.get("in_flight"),
        "uptime_s": int(time.monotonic() - _started_mono),
        "last_requests": recent_requests(limit=8),
    }
    if dump:
        payload["stacks"] = _stack_summaries()
        logger.error("WEB_EVENT_LOOP_STALL", **_public_fields({k: v for k, v in payload.items() if k != "stacks"}))
        logger.error("WEB_EVENT_LOOP_STALL_STACKS", n_threads=len(payload["stacks"]))
        for item in payload["stacks"]:
            logger.error(
                "WEB_EVENT_LOOP_STALL_THREAD",
                thread_id=item["thread_id"],
                frames=item["stack"][:20],
            )
        stored = {k: v for k, v in payload.items() if k != "stacks"}
        stored["top_frames"] = [s["stack"][:6] for s in payload["stacks"][:6]]
        _stalls.append(stored)
    else:
        logger.warning("WEB_EVENT_LOOP_STALL", **_public_fields(payload))
        _stalls.append(payload)


def _watchdog_loop() -> None:
    global _lag_s, _last_dump_mono, _stall_episode
    while not _stop.wait(WATCHDOG_S):
        lag = time.monotonic() - _pulse_mono
        _lag_s = lag
        if lag < STALL_WARN_S:
            _stall_episode = False
            continue
        dump = lag >= STALL_DUMP_S and (time.monotonic() - _last_dump_mono) >= 10.0
        if dump:
            _last_dump_mono = time.monotonic()
            _note_stall(lag, dump=True)
            _stall_episode = True
        elif not _stall_episode:
            _stall_episode = True
            _note_stall(lag, dump=False)


def _sample_loop() -> None:
    while not _stop.wait(SAMPLE_S):
        _samples.append(memory_sample())


async def _pulse_loop() -> None:
    global _pulse_mono
    try:
        while not _stop.is_set():
            _pulse_mono = time.monotonic()
            await asyncio.sleep(PULSE_S)
    except asyncio.CancelledError:
        return


def start_observability(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Start pulse task + watchdog/sample daemon threads. Idempotent."""
    global _watchdog_thread, _sample_thread, _pulse_task, _pulse_mono, _started_mono, _stall_episode
    _stop.clear()
    _stall_episode = False
    _pulse_mono = time.monotonic()
    _started_mono = time.monotonic()
    if os.environ.get("ARIE_TRACEMALLOC") == "1":
        try:
            import tracemalloc

            if not tracemalloc.is_tracing():
                tracemalloc.start(5)
                logger.info("tracemalloc_started", frames=5)
        except Exception:
            logger.exception("tracemalloc_start_failed")
    if _watchdog_thread is None or not _watchdog_thread.is_alive():
        _watchdog_thread = threading.Thread(target=_watchdog_loop, name="arie-loop-watchdog", daemon=True)
        _watchdog_thread.start()
    if _sample_thread is None or not _sample_thread.is_alive():
        _sample_thread = threading.Thread(target=_sample_loop, name="arie-rss-sampler", daemon=True)
        _sample_thread.start()
    running = loop or asyncio.get_running_loop()
    if _pulse_task is None or _pulse_task.done():
        _pulse_task = running.create_task(_pulse_loop(), name="arie-loop-pulse")
    logger.info("web_observability_started")


def stop_observability() -> None:
    global _pulse_task
    _stop.set()
    task = _pulse_task
    _pulse_task = None
    if task is not None:
        task.cancel()
    logger.info("web_observability_stopped")


# --- test helpers ---

def reset_observability_state() -> None:
    _ring.clear()
    _samples.clear()
    _stalls.clear()
    global _in_flight, _lag_s, _pulse_mono, _stall_episode
    with _in_flight_lock:
        _in_flight = 0
    _lag_s = 0.0
    _pulse_mono = time.monotonic()
    _stall_episode = False


def inject_pulse_age(seconds: float) -> None:
    """Backdate the pulse so the watchdog observes a stall. Tests only."""
    global _pulse_mono
    _pulse_mono = time.monotonic() - seconds


def force_stall_check(*, dump: bool = True) -> None:
    lag = time.monotonic() - _pulse_mono
    _note_stall(lag, dump=dump)


class RequestTelemetryMiddleware:
    """ASGI middleware: START/END logs + bounded ring. No query or headers secrets."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        req_id = uuid.uuid4().hex[:10]
        method = str(scope.get("method") or "")
        path = str(scope.get("path") or "")
        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers") or []}
        ua = headers.get("user-agent") or ""
        client = _client_class(path, ua)
        t0 = time.perf_counter()
        rss0 = rss_mb()
        global _in_flight
        with _in_flight_lock:
            _in_flight += 1
            inflight = _in_flight
        logger.info(
            "WEB_REQUEST_START",
            **_public_fields(
                {
                    "request_id": req_id,
                    "ts": time.time(),
                    "method": method,
                    "path": path,
                    "client_class": client,
                    "ua_family": _ua_family(ua),
                    "ua_hash": _ua_hash(ua),
                    "pid": os.getpid(),
                    "rss_mb": rss0,
                    "in_flight": inflight,
                }
            ),
        )
        status_box = {"code": 0}

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                status_box["code"] = int(message.get("status") or 0)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            dt_ms = int((time.perf_counter() - t0) * 1000)
            with _in_flight_lock:
                _in_flight = max(0, _in_flight - 1)
                inflight_end = _in_flight
            entry = {
                "request_id": req_id,
                "ts": time.time(),
                "method": method,
                "path": path,
                "status": status_box["code"],
                "duration_ms": dt_ms,
                "pid": os.getpid(),
                "rss_mb": rss_mb(),
                "client_class": client,
                "ua_family": _ua_family(ua),
                "ua_hash": _ua_hash(ua),
                "in_flight": inflight_end,
                "t_mono": round(time.monotonic(), 3),
            }
            _record_request(entry)
            logger.info("WEB_REQUEST_END", **_public_fields(entry))
