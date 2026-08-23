"""Source package. Registry imports are lazy to avoid circular imports with privacy."""

from __future__ import annotations

from typing import Any

__all__ = ["adapter_map", "all_adapters"]


def __getattr__(name: str) -> Any:
    if name in {"adapter_map", "all_adapters"}:
        from app.sources.registry import adapter_map, all_adapters

        return adapter_map if name == "adapter_map" else all_adapters
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
