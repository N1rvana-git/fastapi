"""Migration safety tests (real Alembic runs on a throw-away SQLite file).

These cover the parts unit tests cannot: the duplicate-e-mail cleanup SQL and the
partial unique index, including a full downgrade.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_REVISION = "b2f4c7d91a30"
HEAD_REVISION = "d4b7e2a9c1f0"


def _alembic(db_path: Path, *args: str) -> None:
    env = os.environ.copy()
    env.update(
        {
            "ENVIRONMENT": "test",
            "DATABASE_URL": f"sqlite+aiosqlite:///{db_path.as_posix()}",
            "SECRET_KEY": "migration-test-secret-key-32chars",
            "TASKS_EAGER": "true",
            "CHAT_API_KEY": "",
            "EMBEDDING_ENABLED": "false",
            "VISION_ENABLED": "false",
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stderr}"


def _seed_duplicates(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.executemany(
            "INSERT INTO users (username, age, email, hashed_password, role, created_at)"
            " VALUES (?, 18, ?, 'x', 'user', CURRENT_TIMESTAMP)",
            [
                ("first", "dup@example.com"),
                ("second", "DUP@example.com"),
                ("third", "dup@example.com"),
                ("nullmail", None),
            ],
        )
        connection.commit()
    finally:
        connection.close()


def _rows(db_path: Path) -> list[tuple[int, str | None]]:
    connection = sqlite3.connect(db_path)
    try:
        return list(connection.execute("SELECT id, email FROM users ORDER BY id"))
    finally:
        connection.close()


def _indexes(db_path: Path) -> set[str]:
    connection = sqlite3.connect(db_path)
    try:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='users'"
            )
        }
    finally:
        connection.close()


def test_duplicate_emails_are_archived_and_indexed(tmp_path: Path) -> None:
    db_path = tmp_path / "migration.db"
    _alembic(db_path, "upgrade", BASE_REVISION)
    _seed_duplicates(db_path)
    _alembic(db_path, "upgrade", "head")

    rows = _rows(db_path)
    emails = [email for _id, email in rows if email is not None]
    assert len({email.lower() for email in emails}) == len(emails)
    # The earliest account keeps its address; later duplicates are archived.
    assert rows[0][1] == "dup@example.com"
    assert rows[1][1] == "DUP@example.com+dup2"
    assert rows[2][1] == "dup@example.com+dup3"
    assert rows[3][1] is None  # null e-mails stay untouched
    assert "users_email_lower_key" in _indexes(db_path)

    # The database now rejects a case-variant duplicate.
    connection = sqlite3.connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO users (username, age, email, hashed_password, role, created_at)"
                " VALUES ('late', 18, 'Dup@Example.com', 'x', 'user', CURRENT_TIMESTAMP)"
            )
    finally:
        connection.close()


def test_unique_index_is_removed_on_downgrade(tmp_path: Path) -> None:
    db_path = tmp_path / "migration_down.db"
    _alembic(db_path, "upgrade", "head")
    assert "users_email_lower_key" in _indexes(db_path)
    _alembic(db_path, "downgrade", BASE_REVISION)
    assert "users_email_lower_key" not in _indexes(db_path)
    # The revision pointer is back at the previous head.
    connection = sqlite3.connect(db_path)
    try:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    finally:
        connection.close()
    assert version == BASE_REVISION
    assert version != HEAD_REVISION
