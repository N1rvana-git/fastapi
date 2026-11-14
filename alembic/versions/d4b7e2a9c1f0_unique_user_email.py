"""unique email (case-insensitive) + duplicate cleanup

The original schema only had a non-unique index on ``users.email``; uniqueness
was enforced in the service layer, which loses every race between two replicas.
This migration:

1. renames every duplicate (keeping the lowest id) to ``<email>+dup<id>`` so no
   data is lost and accounts stay distinguishable;
2. creates a unique functional index on ``lower(email)`` for non-null emails.

``lower(email)`` also prevents ``Alice@x.com`` / ``alice@x.com`` from coexisting.

Revision ID: d4b7e2a9c1f0
Revises: b2f4c7d91a30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4b7e2a9c1f0"
down_revision: Union[str, Sequence[str], None] = "b2f4c7d91a30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "users_email_lower_key"


def upgrade() -> None:
    # --- 1. de-duplicate case-insensitively -------------------------------
    # Keep the earliest account for each lower(email); archive the rest by
    # suffixing their id (reversible, grep-able: email LIKE '%+dup%').
    op.execute(
        r"""
        UPDATE users
        SET email = email || '+dup' || CAST(id AS VARCHAR)
        WHERE email IS NOT NULL
          AND id NOT IN (
              SELECT MIN(id)
              FROM users
              WHERE email IS NOT NULL
              GROUP BY lower(email)
          )
        """
    )

    # --- 2. enforce uniqueness at the database level ----------------------
    op.create_index(
        _INDEX_NAME,
        "users",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
        sqlite_where=sa.text("email IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="users")
