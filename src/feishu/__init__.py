""".. deprecated:: 0.2.0

Replaced by :mod:`src.app.modules.feishu` (``client``, ``service``, ``router``,
``tasks``).

Remove with::

    git rm -r src/feishu
"""

raise ImportError(
    "src.feishu is deprecated and no longer importable. Use src.app.modules.feishu; "
    "see MIGRATION.md (git rm -r src/feishu)."
)
