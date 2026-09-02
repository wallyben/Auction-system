"""Static audit: async FastAPI routes must not run sync SQLAlchemy on the loop."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from typing import Any

from fastapi.routing import APIRoute

from app.main import app

# Tokens that, if present in an async route body without an offload, pin /health.
_BLOCKING = (
    "session.commit",
    "session.rollback",
    "session.flush",
    "session.execute",
    "session.scalars",
    "session.scalar",
    "session.add",
    "session.get",
    "time.sleep",
    "subprocess.",
    "requests.",
    "urllib.request",
    "Path.open",
    "write_text",
    "read_bytes",
)

_OFFLOAD = ("asyncio.to_thread", "to_thread", "isolated_session_async", "run_in_executor")


def _http_routes() -> list[APIRoute]:
    return [route for route in app.routes if isinstance(route, APIRoute)]


def test_health_router_module_is_not_mounted() -> None:
    """app.api.routes.health is a leftover sync /health. It must stay unmounted."""
    paths = {(tuple(r.methods or []), r.path) for r in _http_routes()}
    health_handlers = [r for r in _http_routes() if r.path == "/health"]
    assert health_handlers
    from app.api.routes import ops

    for route in health_handlers:
        assert route.endpoint is ops.health or route.endpoint.__name__ == "health"
        assert inspect.iscoroutinefunction(route.endpoint)


def test_every_async_route_passes_blocking_audit() -> None:
    failures: list[str] = []
    inventory: list[tuple[str, str, str, bool]] = []
    for route in _http_routes():
        endpoint = route.endpoint
        methods = ",".join(sorted(route.methods or []))
        is_async = inspect.iscoroutinefunction(endpoint)
        inventory.append((methods, route.path, endpoint.__name__, is_async))
        if not is_async:
            continue
        source = inspect.getsource(endpoint)
        offloaded = any(token in source for token in _OFFLOAD)
        for token in _BLOCKING:
            if token in source and not offloaded:
                failures.append(f"{methods} {route.path} ({endpoint.__name__}): {token} on event loop")
        if "Depends(get_db)" in source and not offloaded:
            failures.append(f"{methods} {route.path}: async handler Depends(get_db) without offload")
    assert not failures, "async route event-loop violations:\n" + "\n".join(failures)
    assert any(item[1] == "/health" and item[3] for item in inventory)


def test_sync_db_handlers_are_not_coroutines() -> None:
    from app.api.routes import dashboard, ebay_oauth, ebay_webhooks, ops

    sync_db = [
        ops.health_db,
        ops.health_jobs,
        ops.list_opportunities,
        ops.health_evidence,
        dashboard.dashboard,
        ebay_oauth.ebay_oauth_start,
        ebay_oauth.sold_status,
        ebay_webhooks.ebay_account_deletion_challenge,
    ]
    for fn in sync_db:
        assert not inspect.iscoroutinefunction(fn), fn.__name__


def test_webhook_post_offloads_sync_sqlalchemy() -> None:
    from app.api.routes import ebay_webhooks

    assert inspect.iscoroutinefunction(ebay_webhooks.ebay_account_deletion_notice)
    src = inspect.getsource(ebay_webhooks.ebay_account_deletion_notice)
    assert "asyncio.to_thread" in src
    assert "persist_verified_deletion" in src
    persist_src = inspect.getsource(ebay_webhooks.persist_verified_deletion)
    assert "session.commit" in persist_src
    assert not inspect.iscoroutinefunction(ebay_webhooks.persist_verified_deletion)
    assert not inspect.iscoroutinefunction(ebay_webhooks.ebay_account_deletion_challenge)


def test_mixed_pipeline_routes_offload_isolated_session() -> None:
    from app.api.routes import dashboard, ebay_oauth, ops

    for fn in (
        ops.import_csv,
        dashboard.value_this_url,
        dashboard.value_this_item,
        ebay_oauth.ebay_oauth_callback,
        ebay_oauth.ebay_sold_ingest,
        dashboard.upload_owner_sales,
        dashboard.upload_marketplace_sales,
    ):
        assert inspect.iscoroutinefunction(fn), fn.__name__
        src = inspect.getsource(fn)
        assert "to_thread" in src, fn.__name__
        assert "Depends(get_db)" not in src, fn.__name__


def test_dispatch_http_never_enqueues_on_event_loop() -> None:
    from app.jobs import lease

    src = inspect.getsource(lease.dispatch_http)
    assert "asyncio.to_thread" in src
    assert "enqueue_http" in src


def test_offload_helper_opens_its_own_session() -> None:
    from app.web.offload import isolated_session_async

    src = inspect.getsource(isolated_session_async)
    assert "get_session_factory" in src
    assert "asyncio.run" in src
    assert "session.close" in src
    tree = ast.parse(src)
    assert tree.body
