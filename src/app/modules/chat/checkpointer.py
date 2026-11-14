"""LangGraph checkpointer lifecycle.

Per the PDF's Part 3: the checkpointer uses **its own** psycopg3 connection pool,
physically isolated from the SQLAlchemy business pool, so a slow business query
can never block a graph snapshot write.  ``psycopg`` requires
``autocommit=True`` and ``row_factory=dict_row`` for ``setup()`` to create the
checkpoint tables/indexes without transaction-block errors.

When ``POSTGRES_RAW_DSN`` is empty (or no PostgreSQL is available) an
``InMemorySaver`` is used: interrupts still work within one process, which keeps
tests and single-node demos simple.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from src.app.core.config import Settings
from src.app.core.exceptions import FeatureUnavailableError
from src.app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CheckpointerHandle:
    saver: Any
    pool: Any | None
    backend: str

    async def aclose(self) -> None:
        if self.pool is not None:
            try:
                await self.pool.close()
            except Exception:  # pragma: no cover - best effort shutdown
                logger.debug("failed closing checkpointer pool")
        logger.info("checkpointer closed", extra={"ctx_backend": self.backend})


async def build_checkpointer(settings: Settings) -> CheckpointerHandle:
    try:
        if settings.POSTGRES_RAW_DSN:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from psycopg import AsyncConnection
            from psycopg.rows import dict_row
            from psycopg_pool import AsyncConnectionPool

            pool = AsyncConnectionPool(
                conninfo=settings.POSTGRES_RAW_DSN,
                min_size=settings.CHECKPOINTER_POOL_MIN,
                max_size=settings.CHECKPOINTER_POOL_MAX,
                kwargs={
                    "autocommit": True,
                    "row_factory": dict_row,
                    # PgBouncer compatibility: no server-side prepared statements.
                    "prepare_threshold": 0,
                },
                open=False,
            )
            await pool.open()
            await pool.wait()
            # ``row_factory=dict_row`` means rows are dicts, which the generic
            # annotation of AsyncConnectionPool cannot infer from kwargs.
            saver = AsyncPostgresSaver(
                cast("AsyncConnectionPool[AsyncConnection[dict[str, Any]]]", pool)
            )
            await saver.setup()
            logger.info(
                "langgraph checkpointer ready",
                extra={
                    "ctx_backend": "postgres",
                    "ctx_pool_min": settings.CHECKPOINTER_POOL_MIN,
                    "ctx_pool_max": settings.CHECKPOINTER_POOL_MAX,
                },
            )
            return CheckpointerHandle(saver=saver, pool=pool, backend="postgres")

        from langgraph.checkpoint.memory import InMemorySaver

        logger.warning(
            "POSTGRES_RAW_DSN is empty: using in-memory LangGraph checkpoints "
            "(interrupts do not survive a process restart)"
        )
        return CheckpointerHandle(saver=InMemorySaver(), pool=None, backend="memory")
    except ImportError as exc:  # optional extra not installed
        raise FeatureUnavailableError(
            "LangGraph is not installed; install the 'langgraph' extra"
        ) from exc


__all__ = ["CheckpointerHandle", "build_checkpointer"]
