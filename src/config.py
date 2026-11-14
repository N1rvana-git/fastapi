""".. deprecated:: 0.2.0

Compatibility shim. The settings live in :mod:`src.app.core.config` now.

Delete this module together with the other legacy paths listed in
``MIGRATION.md`` once no external script imports them.
"""

from src.app.core.config import BASE_DIR, Settings, get_settings, settings

__all__ = ["BASE_DIR", "Settings", "get_settings", "settings"]
