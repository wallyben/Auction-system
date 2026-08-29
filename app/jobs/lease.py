"""Pipeline job helpers used by the worker.

The web process must enqueue via ``dispatch_http`` / ``enqueue_http`` and must
never execute scan/revalue/sold runners after returning 202.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.jobs.queue import (
    LEASE_SECONDS,
    PIPELINE_LEASE_NAME,
    enqueue_http,
    finish,
    heartbeat,
    lease_status,
    recent_jobs,
)

YIELD_EVERY = 8

# In-process busy flags are retired. The worker/Postgres lease is authoritative.
_busy = False
_busy_name = ""
_busy_job_id: str | None = None


def is_busy() -> bool:
    return False


def memory_status() -> dict[str, object]:
    return {"busy": False, "name": None, "job_id": None, "mode": "worker_queue"}


def release_memory() -> None:
    return None


async def yield_loop() -> None:
    await asyncio.sleep(0)


async def maybe_yield(index: int, *, every: int = YIELD_EVERY) -> None:
    if index > 0 and index % every == 0:
        await yield_loop()


async def dispatch_http(
    name: str,
    trigger: str,
    payload: dict[str, Any] | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """Enqueue only. The optional runner kwarg is ignored on purpose."""
    return enqueue_http(name, trigger, payload)
