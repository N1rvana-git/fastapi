"""HNSW indexes for pgvector embeddings.

Revision ID: e5c8f3b2a1d9
Revises: d4b7e2a9c1f0

Exact nearest-neighbour scans (``ORDER BY embedding <=> ...``) work without an
index, but they are O(n) and become the bottleneck once the catalogue grows.
HNSW gives logarithmic recall/latency on PostgreSQL + pgvector; SQLite has no
pgvector, so the migration is a deliberate no-op there (the app falls back to
lexical search).
"""

from __future__ import annotations

from alembic import op

revision = "e5c8f3b2a1d9"
down_revision = "d4b7e2a9c1f0"
branch_labels = None
depends_on = None

_ITEM_INDEX = "ix_item_embedding_hnsw"
_KNOWLEDGE_INDEX = "ix_knowledge_embedding_hnsw"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_ITEM_INDEX} "
        "ON item USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_KNOWLEDGE_INDEX} "
        "ON knowledge_base USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DROP INDEX IF EXISTS {_ITEM_INDEX}")
    op.execute(f"DROP INDEX IF EXISTS {_KNOWLEDGE_INDEX}")
