from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from extensions.ext_database import db

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str = Field(description="Health status")


class ReadinessResponse(BaseModel):
    status: str = Field(description="Readiness status")
    database: str = Field(description="Database connectivity status")


@router.get("/health", response_model=HealthResponse)
@router.get("/health/live", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness() -> ReadinessResponse:
    is_ready = await db.healthcheck()
    if not is_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ReadinessResponse(status="degraded", database="unreachable").model_dump(),
        )
    return ReadinessResponse(status="ok", database="ready")
