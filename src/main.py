"""ASGI entry point (``uvicorn src.main:app``).

The implementation lives in :mod:`src.app.main`; this shim keeps the historical
import path working for existing deployment scripts.
"""

from src.app.core.compat import ensure_event_loop_policy
from src.app.core.config import get_settings
from src.app.main import app, create_app

# psycopg3 (LangGraph checkpointer) needs the selector loop on Windows, but that
# loop has a ~15.6 ms timer granularity which noticeably slows concurrent
# connection acceptance. Only opt in when the LangGraph runtime is enabled.
if get_settings().AGENT_RUNTIME == "langgraph" or get_settings().LANGGRAPH_ENABLED:
    ensure_event_loop_policy()

__all__ = ["app", "create_app"]
