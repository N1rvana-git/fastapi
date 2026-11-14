"""Request-scoped context.

A single ``contextvars`` store carries the trace id (and a few optional labels)
through middleware, routers, services, repositories and background tasks.  Every
log line and every error payload can therefore be correlated without threading
a ``Request`` object through the whole call stack.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

_trace_id: ContextVar[str] = ContextVar("trace_id", default="")
_request_id: ContextVar[str] = ContextVar("request_id", default="")
_user_id: ContextVar[str] = ContextVar("user_id", default="")
_route: ContextVar[str] = ContextVar("route", default="")

TRACE_HEADER = "X-Trace-ID"
REQUEST_ID_HEADER = "X-Request-ID"


def new_trace_id() -> str:
    return uuid.uuid4().hex


def get_trace_id() -> str:
    return _trace_id.get()


def get_request_id() -> str:
    return _request_id.get()


def get_user_id() -> str:
    return _user_id.get()


def get_route() -> str:
    return _route.get()


def set_user_id(user_id: object) -> Token[str]:
    return _user_id.set(str(user_id) if user_id is not None else "")


def reset_user_id(token: Token[str]) -> None:
    try:
        _user_id.reset(token)
    except ValueError:  # pragma: no cover - token from another context
        pass


@contextmanager
def request_context(
    trace_id: str | None = None,
    request_id: str | None = None,
    route: str = "",
) -> Iterator[str]:
    """Bind the request identifiers for the duration of a request."""

    trace = trace_id or new_trace_id()
    rid = request_id or trace
    t1 = _trace_id.set(trace)
    t2 = _request_id.set(rid)
    t3 = _route.set(route)
    try:
        yield trace
    finally:
        _route.reset(t3)
        _request_id.reset(t2)
        _trace_id.reset(t1)


def context_snapshot() -> dict[str, str]:
    """Copy of the current context, safe to hand to a worker thread/task."""

    return {
        "trace_id": get_trace_id(),
        "request_id": get_request_id(),
        "user_id": get_user_id(),
        "route": get_route(),
    }


@contextmanager
def restored_context(snapshot: dict[str, str]) -> Iterator[None]:
    """Re-apply a snapshot inside a detached task (e.g. asyncio.create_task)."""

    tokens = (
        _trace_id.set(snapshot.get("trace_id", "")),
        _request_id.set(snapshot.get("request_id", "")),
        _user_id.set(snapshot.get("user_id", "")),
        _route.set(snapshot.get("route", "")),
    )
    try:
        yield
    finally:
        _route.reset(tokens[3])
        _user_id.reset(tokens[2])
        _request_id.reset(tokens[1])
        _trace_id.reset(tokens[0])
