from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    """Liveness: the process is up. Never depends on infrastructure."""
    return {"status": "ok", "service": "portableai-api"}


@router.get("/ready")
async def readiness_check(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Readiness: required infrastructure reachable.

    Performs a lightweight SELECT 1 against PostgreSQL. Returns 503 when the
    database is unreachable. Never exposes DB URLs or credentials.
    """
    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - readiness must not raise
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not ready", "database": "unreachable"}
    return {"status": "ready", "database": "ok"}