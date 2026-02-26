"""Health endpoint route."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    """Return service liveness."""
    return {"status": "ok"}
