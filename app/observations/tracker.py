"""Track listing observations. Disappearance is not automatically a sale."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.enums import ObservationClass
from app.models.orm import Listing, ListingObservation


def classify_disappearance(*, had_end_date: bool, ended: bool, explicit_sold: bool) -> ObservationClass:
    if explicit_sold:
        return ObservationClass.LIKELY_SOLD
    if ended or had_end_date:
        return ObservationClass.EXPIRED
    return ObservationClass.UNKNOWN


def record_observation(session: Session, listing: Listing, *, asking: Decimal | None, status: str = "active") -> ListingObservation:
    obs = ListingObservation(
        listing_id=listing.id,
        seen_at=datetime.now(timezone.utc),
        asking_price=asking,
        status=status,
        classification=ObservationClass.ACTIVE.value if status == "active" else ObservationClass.UNKNOWN.value,
    )
    session.add(obs)
    return obs
