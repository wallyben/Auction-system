"""Pluggable image-condition observations.

Photographs are not a mechanical diagnosis. With no provider configured, the
interface returns no findings and does not block the rest of ARIE-CV.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ImageFinding:
    finding: str
    severity: str
    confidence: Decimal
    image_reference: str

    def to_dict(self) -> dict[str, str]:
        return {
            "finding": self.finding,
            "severity": self.severity,
            "confidence": str(self.confidence),
            "image_reference": self.image_reference,
        }


class ConditionAnalyzer(Protocol):
    def analyse(self, image_reference: str) -> tuple[ImageFinding, ...]:
        """Visible observations only. No hidden mechanical claim."""


class UnconfiguredAnalyzer:
    provider = ""

    def analyse(self, image_reference: str) -> tuple[ImageFinding, ...]:
        del image_reference
        return ()


def condition_analysis_enabled() -> bool:
    return bool(os.environ.get("CV_CONDITION_PROVIDER", "").strip())


def analyzer_from_environment() -> ConditionAnalyzer:
    if condition_analysis_enabled():
        # A named provider is a gate, not an implied model. No provider module
        # is bundled, so findings stay empty until one is configured.
        return UnconfiguredAnalyzer()
    return UnconfiguredAnalyzer()


def observe_images(image_references: tuple[str, ...]) -> tuple[ImageFinding, ...]:
    analyzer = analyzer_from_environment()
    found: list[ImageFinding] = []
    for reference in image_references:
        found.extend(analyzer.analyse(reference))
    return tuple(found)
