from fastapi import APIRouter

from database.db import database_exists


router = APIRouter(tags=["health"])


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def readiness() -> dict[str, str]:
    if not database_exists():
        return {"status": "degraded"}
    return {"status": "ready"}
