"""core architecture refactor

Adds everything the modular-monolith refactor introduced:

* ``favourites`` (the router referenced it but no table existed);
* order snapshots (``price``, ``quantity``, ``address``) + ``idempotency_key``;
* conversation ``thread_id`` (with a backfill so existing history keeps working);
* the Human-in-the-Loop approval queue (``agent_approvals``);
* audit timestamps and the indexes the repositories actually query.

Revision ID: b2f4c7d91a30
Revises: c924f1debfb5
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2f4c7d91a30"
down_revision: Union[str, Sequence[str], None] = "c924f1debfb5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------------------------------------------------------- users
    op.add_column(
        "users",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column("users", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    # ----------------------------------------------------------------- item
    op.add_column(
        "item",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column("item", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE item SET is_sold = false WHERE is_sold IS NULL")
    with op.batch_alter_table("item") as batch:
        batch.alter_column(
            "is_sold", existing_type=sa.Boolean(), nullable=False, server_default=sa.text("false")
        )
    op.create_index("item_owner_id_idx", "item", ["owner_id"], unique=False)

    # ----------------------------------------------------------- favourites
    op.create_table(
        "favourites",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "item_id"),
    )

    # --------------------------------------------------------------- orders
    op.add_column(
        "orders",
        sa.Column("quantity", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("orders", sa.Column("price", sa.Float(), nullable=True))
    op.add_column("orders", sa.Column("address", sa.String(length=512), nullable=True))
    op.add_column("orders", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.add_column("orders", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    # Backfill the price snapshot from the listing so historical orders are useful.
    op.execute(
        "UPDATE orders SET price = "
        "(SELECT item.price FROM item WHERE item.id = orders.item_id) "
        "WHERE price IS NULL"
    )
    op.create_index("orders_idempotency_key_idx", "orders", ["idempotency_key"], unique=True)
    op.create_index("orders_buyer_id_idx", "orders", ["buyer_id"], unique=False)
    op.create_index("orders_item_id_idx", "orders", ["item_id"], unique=False)

    # ------------------------------------------------------ chat + approvals
    op.add_column("ai_chat_records", sa.Column("thread_id", sa.String(length=64), nullable=True))
    # Backfill keeps existing conversations addressable by the new SSE layer.
    # NOTE: ``\:main`` escapes the colon, otherwise Alembic parses it as a bind
    # parameter; CAST makes the concatenation portable to PostgreSQL.
    op.execute(
        r"UPDATE ai_chat_records SET thread_id = 'u' || CAST(user_id AS VARCHAR) || '\:main' "
        "WHERE thread_id IS NULL"
    )
    op.create_index("ai_chat_records_thread_id_idx", "ai_chat_records", ["thread_id"], unique=False)
    op.create_index("ai_chat_records_user_id_idx", "ai_chat_records", ["user_id"], unique=False)

    op.create_table(
        "agent_approvals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=True),
        sa.Column("decision_comment", sa.String(length=512), nullable=True),
        sa.Column("resolved_order_id", sa.Integer(), nullable=True),
        sa.Column("decision_by", sa.Integer(), nullable=True),
        sa.Column("notified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="agent_approvals_idempotency_key_key"),
    )
    op.create_index("agent_approvals_thread_id_idx", "agent_approvals", ["thread_id"], unique=False)
    op.create_index("agent_approvals_user_id_idx", "agent_approvals", ["user_id"], unique=False)

    # ------------------------------------------------------------ knowledge
    op.add_column(
        "knowledge_base",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("knowledge_base", "created_at")

    op.drop_index("agent_approvals_user_id_idx", table_name="agent_approvals")
    op.drop_index("agent_approvals_thread_id_idx", table_name="agent_approvals")
    op.drop_table("agent_approvals")

    op.drop_index("ai_chat_records_user_id_idx", table_name="ai_chat_records")
    op.drop_index("ai_chat_records_thread_id_idx", table_name="ai_chat_records")
    op.drop_column("ai_chat_records", "thread_id")

    op.drop_index("orders_item_id_idx", table_name="orders")
    op.drop_index("orders_buyer_id_idx", table_name="orders")
    op.drop_index("orders_idempotency_key_idx", table_name="orders")
    for column in ("updated_at", "idempotency_key", "address", "price", "quantity"):
        op.drop_column("orders", column)

    op.drop_table("favourites")

    op.drop_index("item_owner_id_idx", table_name="item")
    op.drop_column("item", "updated_at")
    op.drop_column("item", "created_at")

    op.drop_column("users", "updated_at")
    op.drop_column("users", "created_at")
