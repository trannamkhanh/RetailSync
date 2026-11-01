"""Health endpoint."""

from fastapi import APIRouter


router = APIRouter(tags=["Health"])


@router.get("/health")
def get_health() -> dict[str, str]:
    return {"status": "ok"}
