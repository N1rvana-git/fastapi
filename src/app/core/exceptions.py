"""Domain errors and their single HTTP mapping.

Rules enforced by this module:

* services and repositories raise **domain** exceptions only - never
  ``fastapi.HTTPException`` - so the same code can be reused from a worker, a
  CLI or a webhook;
* the web layer maps them to a stable error envelope:
  ``{"error": {"code", "message", "trace_id", "details"}, "detail": message}``;
* unexpected exceptions are logged with the trace id and never leak internals.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.app.core.context import get_trace_id
from src.app.core.logging import get_logger, log_extra

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for every expected, mapped failure."""

    code: str = "INTERNAL_ERROR"
    status_code: int = 500
    default_message: str = "Internal server error"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = dict(details or {})
        self.headers = dict(headers or {})
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "trace_id": get_trace_id(),
                "details": self.details,
            },
            # Backwards compatibility for clients built against the old
            # ``{"detail": ...}`` FastAPI shape.
            "detail": self.message,
        }


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    status_code = 422
    default_message = "Request validation failed"


class NotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = 404
    default_message = "Resource not found"


class ConflictError(AppError):
    code = "CONFLICT"
    status_code = 409
    default_message = "Resource conflict"


class IdempotencyConflict(ConflictError):
    code = "IDEMPOTENCY_IN_PROGRESS"
    default_message = "The same request is still being processed"


class PermissionDeniedError(AppError):
    code = "PERMISSION_DENIED"
    status_code = 403
    default_message = "You do not have permission to perform this action"


class UnauthorizedError(AppError):
    code = "UNAUTHORIZED"
    status_code = 401
    default_message = "Not authenticated"


class RateLimitedError(AppError):
    code = "RATE_LIMITED"
    status_code = 429
    default_message = "Too many requests, please slow down"

    def __init__(self, message: str | None = None, *, retry_after: int = 60, **kwargs: Any) -> None:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Retry-After", str(max(1, retry_after)))
        super().__init__(message, headers=headers, **kwargs)


class DependencyUnavailableError(AppError):
    code = "DEPENDENCY_UNAVAILABLE"
    status_code = 503
    default_message = "A required dependency is unavailable"


class FeatureUnavailableError(AppError):
    code = "FEATURE_UNAVAILABLE"
    status_code = 503
    default_message = "This feature is not available in the current deployment"


class PayloadTooLargeError(AppError):
    code = "PAYLOAD_TOO_LARGE"
    status_code = 413
    default_message = "Request payload is too large"


class BusinessRuleViolation(AppError):
    code = "BUSINESS_RULE_VIOLATION"
    status_code = 400
    default_message = "The request violates a business rule"


class OutOfStockError(BusinessRuleViolation):
    code = "OUT_OF_STOCK"
    default_message = "The item is sold out"


class ApprovalRequiredError(ConflictError):
    """Raised when a high-value action needs a human decision.

    The agent runtime turns this into an ``interrupt_required`` SSE event and
    stores a pending approval; it is never shown to the user as a hard failure.
    """

    code = "APPROVAL_REQUIRED"
    default_message = "This action requires human approval"


# --------------------------------------------------------------------------- #
# FastAPI wiring
# --------------------------------------------------------------------------- #
def _response(
    status_code: int, payload: Mapping[str, Any], headers: Mapping[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=dict(payload), headers=dict(headers or {}))


def register_exception_handlers(app: FastAPI) -> None:
    """Attach every handler once; called from ``create_app``."""

    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        log = logger.warning if exc.status_code < 500 else logger.error
        log(
            "domain error",
            extra=log_extra(
                event="app_error",
                error_code=exc.code,
                status_code=exc.status_code,
                error_detail=exc.details,
            ),
        )
        return _response(exc.status_code, exc.to_payload(), exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = {"errors": _jsonable_errors(exc.errors())}
        error = ValidationError(details=details)
        return _response(error.status_code, error.to_payload())

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _CODE_BY_STATUS.get(exc.status_code, "HTTP_ERROR")
        payload = {
            "error": {
                "code": code,
                "message": str(exc.detail),
                "trace_id": get_trace_id(),
                "details": {},
            },
            "detail": exc.detail,
        }
        return _response(exc.status_code, payload, getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        trace_id = get_trace_id()
        logger.exception("unhandled exception", extra=log_extra(event="unhandled_exception"))
        return _response(
            500,
            {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Internal server error",
                    "trace_id": trace_id,
                    "details": {},
                },
                "detail": "Internal server error",
            },
        )


_CODE_BY_STATUS = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def _jsonable_errors(errors: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """``RequestValidationError.errors()`` can contain non-JSON values (e.g. bytes)."""

    cleaned: list[dict[str, Any]] = []
    for item in errors:
        record = {key: value for key, value in item.items() if key != "input"}
        record["input"] = repr(item.get("input"))[:200]
        cleaned.append(record)
    return cleaned


__all__ = [
    "AppError",
    "ApprovalRequiredError",
    "BusinessRuleViolation",
    "ConflictError",
    "DependencyUnavailableError",
    "FeatureUnavailableError",
    "IdempotencyConflict",
    "NotFoundError",
    "OutOfStockError",
    "PayloadTooLargeError",
    "PermissionDeniedError",
    "RateLimitedError",
    "UnauthorizedError",
    "ValidationError",
    "register_exception_handlers",
]
