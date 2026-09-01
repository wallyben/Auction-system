"""Cheap process-resource snapshot. Never touch the database."""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from app.core.process import process_role


def rss_mb() -> float | None:
    """Current resident set in MiB. Prefers /proc; falls back to ru_maxrss."""
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            pages = int(handle.read().split()[1])
        return round(pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024), 1)
    except Exception:
        try:
            import resource

            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # Linux reports KB; macOS reports bytes.
            if rss > 10_000_000:
                return round(rss / (1024 * 1024), 1)
            return round(rss / 1024, 1)
        except Exception:
            return None


def thread_count() -> int:
    try:
        return len(os.listdir("/proc/self/task"))
    except Exception:
        return threading.active_count()


def cpu_times() -> tuple[float | None, float | None]:
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        return round(usage.ru_utime, 3), round(usage.ru_stime, 3)
    except Exception:
        return None, None


def process_runtime_snapshot() -> dict[str, Any]:
    user_s, system_s = cpu_times()
    return {
        "process_role": process_role(),
        "pid": os.getpid(),
        "rss_mb": rss_mb(),
        "threads": thread_count(),
        "cpu_user_s": user_s,
        "cpu_system_s": system_s,
        "monotonic_s": round(time.monotonic(), 3),
    }
