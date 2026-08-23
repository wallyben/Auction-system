"""Canonical product catalogue for cross-market matching. Public model names only."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CatalogueSku:
    key: str
    brand: str
    family: str
    model: str
    variant: str
    category: str
    release_year: int | None
    aliases: tuple[str, ...]
    attributes: dict[str, str] = field(default_factory=dict)


CATALOGUE: tuple[CatalogueSku, ...] = (
    CatalogueSku("sony|fe-24-70-gm-ii", "Sony", "GM", "FE 24-70mm GM II", "GM II", "lenses", 2022, ("24-70 gm ii", "24-70 gm2", "2470gm2", "sel2470gm2")),
    CatalogueSku("sony|fe-24-70-gm", "Sony", "GM", "FE 24-70mm GM", "GM I", "lenses", 2016, ("24-70 gm", "sel2470gm")),
    CatalogueSku("sony|a7 iv", "Sony", "Alpha", "A7 IV", "IV", "cameras", 2021, ("a7iv", "ilce-7m4", "a7m4")),
    CatalogueSku("apple|macbook pro 14 m3", "Apple", "MacBook", "MacBook Pro 14 M3", "M3", "computing", 2023, ("mbp 14 m3",)),
    CatalogueSku("apple|macbook pro 14 m2", "Apple", "MacBook", "MacBook Pro 14 M2", "M2", "computing", 2023, ("mbp 14 m2",)),
    CatalogueSku("sony|ps5 slim", "Sony", "PlayStation", "PS5 slim", "disc", "gaming", 2023, ("playstation 5 slim",)),
    CatalogueSku("nvidia|rtx 4070", "NVIDIA", "GeForce", "RTX 4070", "", "gpu", 2023, ("4070",)),
    CatalogueSku("nvidia|rtx 4080 super", "NVIDIA", "GeForce", "RTX 4080 SUPER", "SUPER", "gpu", 2024, ("4080 super",)),
    CatalogueSku("nvidia|rtx 4080", "NVIDIA", "GeForce", "RTX 4080", "", "gpu", 2022, ("4080",)),
    CatalogueSku("pioneer|ddj-1000", "Pioneer", "DDJ", "DDJ-1000", "", "music_dj", 2019, ("ddj1000",)),
    CatalogueSku("shure|sm7b", "Shure", "SM", "SM7B", "", "pro_av", 2001, ("sm7 b",)),
)


def lookup_catalogue(text: str) -> CatalogueSku | None:
    blob = (text or "").lower()
    # Longer aliases first so SUPER beats base 4080 and GM II beats GM.
    ranked = sorted(CATALOGUE, key=lambda sku: max((len(a) for a in sku.aliases), default=0), reverse=True)
    for sku in ranked:
        needles = (sku.model.lower(), sku.key.split("|")[-1], *sku.aliases)
        if any(needle and needle in blob for needle in needles):
            if sku.variant == "SUPER" and "super" not in blob:
                continue
            if sku.variant == "GM II" and "gm ii" not in blob and "gm2" not in blob:
                continue
            if sku.key.endswith("|rtx 4080") and "super" in blob:
                continue
            if sku.key.endswith("|fe-24-70-gm") and ("gm ii" in blob or "gm2" in blob):
                continue
            return sku
    return None
