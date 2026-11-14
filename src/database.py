""".. deprecated:: 0.2.0

Compatibility shim. Database wiring lives in :mod:`src.app.core.database` now;
the engine is owned by ``AppContainer`` and comes from the FastAPI lifespan.

Prefer::

    from src.app.core.database import Base, get_database

    async with get_database().session() as session: ...
"""

from src.app.core.database import NAMING_CONVENTION, Base, get_database, import_all_models

__all__ = ["NAMING_CONVENTION", "Base", "get_database", "import_all_models"]
