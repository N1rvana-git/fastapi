"""The HNSW migration must be PostgreSQL-only and reversible."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "e5c8f3b2a1d9_hnsw_embedding_indexes.py"
)


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("hnsw_migration", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeOp:
    def __init__(self, dialect: str) -> None:
        self.dialect = dialect
        self.statements: list[str] = []

    def get_bind(self) -> Any:
        return type("Bind", (), {"dialect": type("Dialect", (), {"name": self.dialect})()})()

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


def test_hnsw_indexes_are_created_on_postgres(monkeypatch: Any) -> None:
    module = _load()
    fake = _FakeOp("postgresql")
    monkeypatch.setattr(module, "op", fake)

    module.upgrade()
    assert len(fake.statements) == 2
    assert all("USING hnsw" in statement for statement in fake.statements)
    assert all("vector_cosine_ops" in statement for statement in fake.statements)

    fake.statements.clear()
    module.downgrade()
    assert len(fake.statements) == 2
    assert all(statement.startswith("DROP INDEX IF EXISTS") for statement in fake.statements)


def test_hnsw_migration_is_a_noop_on_sqlite(monkeypatch: Any) -> None:
    module = _load()
    fake = _FakeOp("sqlite")
    monkeypatch.setattr(module, "op", fake)

    module.upgrade()
    module.downgrade()
    assert fake.statements == []
