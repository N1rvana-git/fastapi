"""Async worker process entry point.

    python -m src.worker

Consumes the Redis task stream with a consumer group, so the web pods stay small
and heavy work (embeddings, Feishu replies, notifications) scales independently.
Under Kubernetes this is the same image with a different command, and the
liveness probe is the process itself.
"""

from __future__ import annotations

import asyncio
import signal
import sys

from src.app.container import AppContainer, set_container
from src.app.core.config import get_settings
from src.app.core.database import import_all_models, set_database
from src.app.core.logging import configure_logging, get_logger, log_extra
from src.app.core.tasks import TaskWorker
from src.app.task_registry import import_task_modules

logger = get_logger(__name__)


async def run_worker(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    configure_logging(settings)
    import_task_modules()
    import_all_models()

    container = AppContainer.create(settings)
    await container.startup()
    set_container(container)
    set_database(container.database)
    try:
        worker = TaskWorker(settings=settings, redis_manager=container.redis)
        await worker.run(stop_event)
    finally:
        set_container(None)
        set_database(None)
        await container.shutdown()


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def _stop(*_: object) -> None:
        logger.info("shutdown signal received", extra=log_extra(event="worker_stop_signal"))
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except (NotImplementedError, RuntimeError):  # Windows / non-main thread
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop_event.set))


async def main() -> int:
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    settings = get_settings()
    configure_logging(settings)
    if not settings.TASKS_ENABLED:
        logger.error("TASKS_ENABLED=false: refusing to start the worker")
        return 2
    await run_worker(stop_event)
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    from src.app.core.compat import ensure_event_loop_policy

    if get_settings().AGENT_RUNTIME == "langgraph" or get_settings().LANGGRAPH_ENABLED:
        ensure_event_loop_policy()
    sys.exit(asyncio.run(main()))
