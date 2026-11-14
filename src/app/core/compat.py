"""Runtime compatibility shims for platform quirks.

Windows' default ``ProactorEventLoop`` cannot be used by psycopg3's async
connections, which the LangGraph checkpointer requires.  Uvicorn/uvloop on Linux
is unaffected, so this only switches the policy on Windows and only at process
start-up (before any loop exists).
"""

from __future__ import annotations

import asyncio
import sys

from src.app.core.logging import get_logger

logger = get_logger(__name__)


def ensure_event_loop_policy() -> None:
    if sys.platform != "win32":
        return
    policy_factory = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy_factory is None:  # pragma: no cover - very old Python
        return
    current = asyncio.get_event_loop_policy()
    if not isinstance(current, policy_factory):
        asyncio.set_event_loop_policy(policy_factory())
        logger.info("switched to WindowsSelectorEventLoopPolicy (psycopg3 requirement)")


__all__ = ["ensure_event_loop_policy"]
