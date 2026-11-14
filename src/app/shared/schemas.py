"""Shared API schemas: errors, health and generic envelopes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    trace_id: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Stable error contract for every 4xx/5xx response."""

    error: ErrorBody
    detail: str | None = None


class LivenessResponse(BaseModel):
    status: str = "ok"
    version: str
    uptime_seconds: float


class CheckResult(BaseModel):
    name: str
    ok: bool
    latency_ms: float
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: str
    checks: list[CheckResult]
    version: str
    environment: str
    timestamp: datetime


class MessageResponse(BaseModel):
    message: str


__all__ = [
    "CheckResult",
    "ErrorBody",
    "ErrorResponse",
    "LivenessResponse",
    "MessageResponse",
    "ReadinessResponse",
]
