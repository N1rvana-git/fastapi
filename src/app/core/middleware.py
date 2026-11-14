"""Pure ASGI middleware.

``BaseHTTPMiddleware`` is deliberately avoided: it wraps every response in an
extra task and buffers streaming bodies, which measurably hurts throughput and
breaks long-lived SSE streams.  Everything here is written against the raw
``(scope, receive, send)`` interface.

Order matters (outermost first, see ``create_app``):

    RequestContext  -> assigns trace id into contextvars
    AccessLog       -> structured access log with latency
    SecurityHeaders -> cheap hardening headers
    BodySizeLimit   -> rejects oversized bodies before parsing
    CORS            -> Starlette's own pure-ASGI implementation
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.app.core.config import Settings
from src.app.core.context import (
    REQUEST_ID_HEADER,
    TRACE_HEADER,
    get_request_id,
    get_trace_id,
    request_context,
)
from src.app.core.logging import get_logger, log_extra

logger = get_logger("app.access")

_TRACE_RE = re.compile(r"^[A-Za-z0-9._:-]{8,64}$")


def _header(scope: Scope, name: bytes) -> str | None:
    headers: list[tuple[bytes, bytes]] = scope.get("headers") or []
    for key, value in headers:
        if key == name:
            return value.decode("latin-1")
    return None


def _client(scope: Scope) -> str:
    client = scope.get("client")
    if not client:
        return "-"
    host, _, port = (
        (client[0], client[1], client[2]) if len(client) > 2 else (client[0], None, None)
    )
    return f"{host}:{port}" if port else str(host)


class RequestContextMiddleware:
    """Assign a trace id (propagating an inbound one when sane)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = _header(scope, TRACE_HEADER.lower().encode()) or _header(scope, b"x-request-id")
        trace_id = inbound.strip() if inbound and _TRACE_RE.match(inbound.strip()) else None
        request_id = _header(scope, b"x-request-id") or trace_id

        with request_context(
            trace_id=trace_id, request_id=request_id, route=_path(scope)
        ) as assigned:
            state = scope.setdefault("state", {})
            state["trace_id"] = assigned
            state["request_id"] = get_request_id() or assigned

            async def send_with_trace(message: Message) -> None:
                if message["type"] == "http.response.start":
                    headers = MutableHeaders(scope=message)
                    headers[TRACE_HEADER] = assigned
                    headers[REQUEST_ID_HEADER] = get_request_id() or assigned
                await send(message)

            await self.app(scope, receive, send_with_trace)


class AccessLogMiddleware:
    """One structured log line per request, including streams and errors."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.exclude = settings.log_access_exclude

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or _path(scope) in self.exclude:
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status_code = 500
        response_bytes = 0
        failed = False

        async def capture(message: Message) -> None:
            nonlocal status_code, response_bytes
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            elif message["type"] == "http.response.body":
                response_bytes += len(message.get("body", b"") or b"")
            await send(message)

        try:
            await self.app(scope, receive, capture)
        except Exception:
            failed = True
            raise
        finally:
            # Exactly one access-log line per request, success or failure.
            duration_ms = (time.perf_counter() - started) * 1000
            log = logger.error if failed or status_code >= 500 else logger.info
            log(
                "request completed",
                extra=log_extra(
                    event="http_request",
                    method=scope.get("method"),
                    path=_path(scope),
                    status_code=status_code,
                    duration_ms=round(duration_ms, 2),
                    response_bytes=response_bytes,
                    client=_client(scope),
                    failed=failed,
                ),
                exc_info=failed,
            )
            _record_metric(scope.get("method"), status_code, duration_ms)


class SecurityHeadersMiddleware:
    """Cheap, high-value response hardening."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.hsts = settings.HSTS_ENABLED

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def add_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
                if self.hsts:
                    headers.setdefault(
                        "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
                    )
            await send(message)

        await self.app(scope, receive, add_headers)


class BodySizeLimitMiddleware:
    """Reject oversized payloads early (also covers chunked uploads)."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.max_bytes = settings.MAX_REQUEST_BYTES

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _header(scope, b"content-length")
        if declared and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b"") or b"")
                if received > self.max_bytes:
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "PAYLOAD_TOO_LARGE",
                    "message": f"Request body exceeds {self.max_bytes} bytes",
                    "trace_id": get_trace_id(),
                    "details": {"max_bytes": self.max_bytes},
                },
                "detail": f"Request body exceeds {self.max_bytes} bytes",
            },
        )
        await response(scope, receive, send)


class _BodyTooLarge(Exception):
    pass


# --------------------------------------------------------------------------- #
# Optional Prometheus metrics (no hard dependency)
# --------------------------------------------------------------------------- #
_HTTP_REQUESTS: Any | None = None
_HTTP_LATENCY: Any | None = None
_metrics_ready = False


def _record_metric(method: str | None, status_code: int, duration_ms: float) -> None:
    global _HTTP_REQUESTS, _HTTP_LATENCY, _metrics_ready
    if not _metrics_ready:
        _metrics_ready = True
        try:  # pragma: no cover - depends on optional package
            from prometheus_client import Counter, Histogram

            _HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "status"])
            _HTTP_LATENCY = Histogram("http_request_duration_seconds", "HTTP latency", ["method"])
        except Exception:
            _HTTP_REQUESTS = None
    if _HTTP_REQUESTS is None or _HTTP_LATENCY is None:
        return
    try:  # pragma: no cover
        _HTTP_REQUESTS.labels(method=method or "UNKNOWN", status=str(status_code)).inc()
        _HTTP_LATENCY.labels(method=method or "UNKNOWN").observe(duration_ms / 1000)
    except Exception:
        return


def _path(scope: Scope) -> str:
    return str(scope.get("path", ""))


Middleware = Callable[[ASGIApp], Awaitable[None]]

__all__ = [
    "AccessLogMiddleware",
    "BodySizeLimitMiddleware",
    "RequestContextMiddleware",
    "SecurityHeadersMiddleware",
]
