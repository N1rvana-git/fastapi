"""Liveness and readiness probes.

``/health/live`` answers "is this process alive?" and must never touch a
dependency.  ``/health/ready`` answers "can this replica serve traffic?" and
checks the database (always) plus Redis (only when it is declared required).
The old single ``/health`` endpoint mixed both concerns, so a slow database made
Kubernetes restart perfectly healthy pods.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request, status
from starlette.responses import JSONResponse

from src.app.shared.schemas import CheckResult, LivenessResponse, ReadinessResponse

router = APIRouter(tags=["health"])

_REQUIRED_CHECKS = {"database"}


@router.get("/health/live", response_model=LivenessResponse, summary="Process liveness")
async def live(request: Request) -> LivenessResponse:
    container = request.app.state.container
    return LivenessResponse(
        status="ok",
        version=request.app.state.settings.APP_VERSION,
        uptime_seconds=round(container.uptime_seconds, 2),
    )


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
    summary="Dependency readiness",
)
async def ready(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    container = request.app.state.container
    raw_checks = await container.readiness()
    required = set(_REQUIRED_CHECKS)
    if settings.REDIS_REQUIRED:
        required.add("redis")

    checks = [
        CheckResult(name=name, ok=ok, latency_ms=round(latency, 2), detail=detail)
        for name, ok, latency, detail in raw_checks
    ]
    failing = [check for check in checks if check.name in required and not check.ok]
    ready_ok = not failing
    payload = ReadinessResponse(
        status="ok" if ready_ok else "degraded",
        checks=checks,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(UTC),
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK if ready_ok else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=payload.model_dump(mode="json"),
    )


@router.get("/health", summary="Legacy health endpoint (liveness semantics)")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


__all__ = ["router"]
