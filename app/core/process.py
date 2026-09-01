"""Which Render process this interpreter is.

WEB: HTTP only. Never owns APScheduler or pipeline execution.
WORKER: durable consumer + scheduler + process heartbeat.
"""

from __future__ import annotations

import os

ROLE_WEB = "web"
ROLE_WORKER = "worker"


def process_role() -> str:
    value = (os.environ.get("ARIE_PROCESS") or ROLE_WEB).strip().lower()
    if value == ROLE_WORKER:
        return ROLE_WORKER
    return ROLE_WEB


def is_web_process() -> bool:
    return process_role() == ROLE_WEB


def is_worker_process() -> bool:
    return process_role() == ROLE_WORKER
