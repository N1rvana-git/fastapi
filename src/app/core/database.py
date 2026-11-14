"""Database engine and session management (SQLAlchemy 2.0, async only).

Design decisions:

* a single ``AsyncEngine`` per process, created in the lifespan and disposed on
  shutdown (``pool_pre_ping`` protects against server-side idle kills);
* ``expire_on_commit=False`` so ORM objects stay usable after commit without
  triggering async lazy loads (the classic ``MissingGreenlet`` trap);
* sessions are short-lived: the web dependency closes them at the end of the
  request, background tasks open their own, so a long SSE stream never pins a
  connection (this was a real pool-exhaustion bug in the previous code).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

from src.app.core.config import Settings
from src.app.core.logging import get_logger

logger = get_logger(__name__)

NAMING_CONVENTION = {
    "ix": "%(column_0_label)s_idx",
    "uq": "%(table_name)s_%(column_0_name)s_key",
    "ck": "%(table_name)s_%(column_0_name)s_check",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    """Declarative base shared by every module's models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Database:
    """Owns the engine + session factory and their lifecycle."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine: AsyncEngine = create_async_engine(
            settings.DATABASE_URL, **self._engine_kwargs(settings)
        )
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        self._closed = False

    @staticmethod
    def _engine_kwargs(settings: Settings) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "echo": settings.DB_ECHO,
            "pool_pre_ping": settings.DB_PRE_PING,
        }
        url = settings.DATABASE_URL
        if url.startswith("sqlite"):
            # SQLite has no server-side pool; in-memory DBs must share one
            # connection or every checkout would see an empty database.
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 10}
            if ":memory:" in url:
                kwargs["poolclass"] = StaticPool
            return kwargs
        kwargs.update(
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_recycle=settings.DB_POOL_RECYCLE,
            connect_args={
                "timeout": settings.DB_CONNECT_TIMEOUT,
                "server_settings": {
                    "application_name": settings.APP_NAME,
                    "statement_timeout": str(settings.DB_STATEMENT_TIMEOUT_MS),
                },
            },
        )
        return kwargs

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Short-lived session; rolls back on error, always closes."""

        session = self.session_factory()
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def ping(self, timeout: float = 2.0) -> None:
        """Raise when the database is not reachable within ``timeout`` seconds."""

        async def _ping() -> None:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))

        await asyncio.wait_for(_ping(), timeout=timeout)

    async def create_all(self) -> None:
        """Test/bootstrap helper. Production schema changes go through Alembic."""

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.engine.dispose()
        logger.info("database engine disposed")


_database: Database | None = None


def set_database(database: Database | None) -> None:
    """Register the process-wide database (called from the lifespan)."""

    global _database
    _database = database


def get_database() -> Database:
    if _database is None:  # pragma: no cover - programming error
        raise RuntimeError("Database is not initialised; did the lifespan run?")
    return _database


def import_all_models() -> None:
    """Import every module's models so ``Base.metadata`` is complete.

    Alembic and the test suite rely on this side effect.
    """

    from src.app.modules.chat import models as _chat_models  # noqa: F401
    from src.app.modules.items import models as _item_models  # noqa: F401
    from src.app.modules.knowledge import models as _knowledge_models  # noqa: F401
    from src.app.modules.orders import models as _order_models  # noqa: F401
    from src.app.modules.users import models as _user_models  # noqa: F401


def table_names(tables: Iterable[object] | None = None) -> list[str]:
    return sorted(table.name for table in (tables or Base.metadata.sorted_tables))
