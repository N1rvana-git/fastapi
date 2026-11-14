"""ASGI entry point (``uvicorn src.main:app``).

The implementation lives in :mod:`src.app.main`; this shim keeps the historical
import path working for existing deployment scripts.
"""

from src.app.main import app, create_app

__all__ = ["app", "create_app"]
