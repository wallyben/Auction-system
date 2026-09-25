"""Process-local Irish market book. Postgres is used when a session is supplied."""

from __future__ import annotations

import threading

from app.domains.vehicles.market import MarketBook, MarketObservation

_LOCK = threading.Lock()
_BOOK = MarketBook()


def add_observations(observations: list[MarketObservation]) -> tuple[int, int]:
    inserted = 0
    duplicates = 0
    with _LOCK:
        for observation in observations:
            try:
                _BOOK.append(observation)
            except ValueError:
                duplicates += 1
                continue
            inserted += 1
    return inserted, duplicates


def current_book() -> MarketBook:
    with _LOCK:
        return MarketBook(observations=list(_BOOK.observations))


def clear_book() -> None:
    global _BOOK
    with _LOCK:
        _BOOK = MarketBook()
