"""Run mixed async-HTTP + sync-SQLAlchemy work off the uvicorn event loop.

A FastAPI ``async def`` handler that uses a SQLAlchemy Session (even one created
by a sync ``Depends``) still executes ``session.execute`` on the event loop.
That pins ``/health``. These helpers create a short-lived session on a worker
thread and drive any nested awaits with a private event loop.

Do not share a Session across threads. Do not call these from a thread that
already has a running event loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from sqlalchemy.orm import Session

T = TypeVar("T")


def isolated_session_async(factory: Callable[[Session], Coroutine[Any, Any, T]]) -> T:
    """Open a session, ``asyncio.run`` the coroutine, commit/rollback, close."""
    from app.db.session import get_session_factory

    session = get_session_factory()()
    try:
        result = asyncio.run(factory(session))
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
