"""ASGI entry point (``uvicorn src.main:app``).

The implementation lives in :mod:`src.app.main`; this shim keeps the historical
import path working for existing deployment scripts.
"""

from src.app.core.compat import ensure_event_loop_policy
from src.app.main import app, create_app

# Must run before uvicorn creates its event loop (psycopg3 + Windows).
ensure_event_loop_policy()

__all__ = ["app", "create_app"]
