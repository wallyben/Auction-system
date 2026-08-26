"""Saved scanning strategies for Tier-1 goods."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import ScanStrategy

DEFAULTS = (
    {
        "name": "Sony GM lenses under €900",
        "categories": ["lenses"],
        "brands": ["Sony"],
        "keywords": ["24-70 gm", "70-200 gm", "16-35 gm"],
        "excluded_keywords": ["gm ii replica"],
        "min_price": Decimal("200"),
        "max_price": Decimal("900"),
    },
    {
        "name": "MacBook Pro M-series under €1,000",
        "categories": ["computing"],
        "brands": ["Apple"],
        "keywords": ["macbook pro m1", "macbook pro m2", "macbook pro m3"],
        "excluded_keywords": ["parts", "locked"],
        "min_price": Decimal("350"),
        "max_price": Decimal("1000"),
    },
    {
        "name": "DJ controllers €200–€1,500",
        "categories": ["music_dj"],
        "brands": ["Pioneer", "Pioneer DJ", "Allen & Heath"],
        "keywords": ["ddj", "xone", "cdj"],
        "excluded_keywords": ["parts"],
        "min_price": Decimal("200"),
        "max_price": Decimal("1500"),
    },
    {
        "name": "PlayStation 5 bundles",
        "categories": ["gaming"],
        "brands": ["Sony"],
        "keywords": ["ps5", "playstation 5"],
        "excluded_keywords": ["digital only account"],
        "min_price": Decimal("200"),
        "max_price": Decimal("700"),
    },
    {
        "name": "GPU opportunities",
        "categories": ["gpu"],
        "brands": ["NVIDIA", "AMD"],
        "keywords": ["rtx 4070", "rtx 4080", "rtx 5070"],
        "excluded_keywords": ["super fake"],
        "min_price": Decimal("250"),
        "max_price": Decimal("1200"),
    },
)


def seed_strategies(session: Session) -> None:
    existing = {row.name for row in session.scalars(select(ScanStrategy)).all()}
    for spec in DEFAULTS:
        if spec["name"] in existing:
            continue
        session.add(
            ScanStrategy(
                name=spec["name"],
                categories=spec["categories"],
                brands=spec["brands"],
                keywords=spec["keywords"],
                excluded_keywords=spec["excluded_keywords"],
                min_price=spec["min_price"],
                max_price=spec["max_price"],
                countries=["IE", "GB", "DE", "FR", "NL"],
                sources=["ebay_browse", "csv_import", "manual"],
                min_expected_profit=Decimal("40"),
                min_roi=Decimal("0.20"),
                max_days=45,
                min_confidence=Decimal("0.70"),
            )
        )
    session.flush()
