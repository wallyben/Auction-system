"""Replaceable evidence providers. Never convert asking or aggregates into fake tickets."""

from __future__ import annotations

from typing import Protocol

from app.evidence.classes import EvidenceRecord


class EvidenceProvider(Protocol):
    name: str
    source_type: str

    async def search_evidence(
        self, product: str, market: str, condition: str, *, limit: int = 20
    ) -> list[EvidenceRecord]: ...

    async def healthcheck(self) -> dict[str, object]: ...
