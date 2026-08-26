"""Adapter contract tests. Blocked sources must not claim LIVE without proof."""

from app.sources.base import SourceAdapter
from app.sources.registry import all_adapters


def test_every_adapter_exposes_contract() -> None:
    adapters = all_adapters()
    assert adapters
    ids = [adapter.source_id for adapter in adapters]
    assert len(ids) == len(set(ids))
    for adapter in adapters:
        assert isinstance(adapter, SourceAdapter)
        assert adapter.source_id
        assert adapter.display_name
        assert hasattr(adapter, "healthcheck")
        assert hasattr(adapter, "search")
        assert hasattr(adapter, "incremental_scan")


def test_known_blocked_sources_are_registered() -> None:
    by_id = {adapter.source_id: adapter for adapter in all_adapters()}
    for source_id in ("donedeal", "adverts_ie", "wilsons", "john_pye", "cex_ie"):
        assert source_id in by_id
        assert not by_id[source_id].official_api
