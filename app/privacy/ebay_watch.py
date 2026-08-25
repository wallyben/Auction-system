"""Privacy-safe eBay webhook event log for `make ebay-notification-watch`.

Never write tokens, signatures, payloads, usernames, or challenge codes.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger("arie.webhooks.ebay.watch")

WATCH_EVENTS = (
    "EBAY_CHALLENGE_RECEIVED",
    "EBAY_CHALLENGE_RESPONDED_200",
    "EBAY_NOTIFICATION_ENDPOINT_VERIFIED",
)

_FORBIDDEN = {
    "token",
    "verification_token",
    "secret",
    "signature",
    "payload",
    "body",
    "username",
    "userid",
    "eias",
    "eiastoken",
    "challenge_code",
    "challengecode",
    "authorization",
}


def watch_log_path() -> Path:
    override = (os.environ.get("EBAY_NOTIFICATION_WATCH_LOG") or "").strip()
    if override:
        return Path(override)
    return Path("artifacts/runtime/ebay_notification_events.jsonl")


def record_watch_event(event: str, **fields: Any) -> None:
    """Append one privacy-safe event. Failures are swallowed so the webhook still answers."""
    safe = {key: value for key, value in fields.items() if key.lower() not in _FORBIDDEN}
    payload = {
        "event": event,
        "ts": datetime.now(timezone.utc).isoformat(),
        **safe,
    }
    logger.info(event, **safe)
    path = watch_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, default=str) + "\n")
    except OSError:
        return


def watch_events(*, timeout_seconds: float = 0) -> int:
    """Tail the watch log and print only event names / safe fields.

    timeout_seconds=0 follows until interrupted.
    """
    path = watch_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    print("Watching privacy-safe eBay webhook events (token values are never printed).")
    print(f"log={path}")
    print("Expected on portal Save:")
    for name in WATCH_EVENTS:
        print(f"  {name}")
    started = time.monotonic()
    offset = 0
    # Replay existing lines first so a just-received challenge is visible.
    try:
        offset = _emit_new_lines(path, 0)
    except OSError as exc:
        print(f"watch_log_unreadable error={type(exc).__name__}")
        return 1
    while True:
        if timeout_seconds and (time.monotonic() - started) >= timeout_seconds:
            return 0
        try:
            offset = _emit_new_lines(path, offset)
        except OSError:
            time.sleep(0.25)
            continue
        time.sleep(0.25)


def _emit_new_lines(path: Path, offset: int) -> int:
    data = path.read_bytes()
    if len(data) < offset:
        offset = 0
    chunk = data[offset:]
    if not chunk:
        return offset
    text = chunk.decode("utf-8", errors="replace")
    if not text.endswith("\n"):
        # Incomplete last line; wait for the rest.
        keep = text.rsplit("\n", 1)
        if len(keep) == 1:
            return offset
        complete, _partial = keep[0] + "\n", keep[1]
        text = complete
        chunk = text.encode("utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        event = str(payload.get("event") or "")
        extra = {
            key: value
            for key, value in payload.items()
            if key not in {"event", "ts"} and key.lower() not in _FORBIDDEN
        }
        if extra:
            safe = " ".join(f"{key}={value}" for key, value in extra.items())
            print(f"{event} {safe}")
        else:
            print(event)
    return offset + len(chunk)
