"""ARIE-CV commercial-vehicle acquisition intelligence.

Deterministic money, tax, identity, and gate logic lives here.
The camera pipeline is not imported.
"""

from app.domains.vehicles.evaluate import evaluate_vehicle

__all__ = ["evaluate_vehicle"]
