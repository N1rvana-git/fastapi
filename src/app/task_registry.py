"""Import task modules for their registration side effect.

Called by ``create_app`` (so eager/in-process execution works) and by the worker
process (so it knows every task).  Kept separate from :mod:`src.app.core.tasks`
to avoid the core layer importing domain modules.
"""

from __future__ import annotations

_IMPORTED = False


def import_task_modules() -> None:
    global _IMPORTED
    if _IMPORTED:
        return
    from src.app.modules.chat import tasks as _chat_tasks  # noqa: F401
    from src.app.modules.feishu import tasks as _feishu_tasks  # noqa: F401
    from src.app.modules.items import tasks as _item_tasks  # noqa: F401

    _IMPORTED = True


__all__ = ["import_task_modules"]
