"""enable_pgvector_extension

Revision ID: ce467137221f
Revises: 0d8fae5b62a8
Create Date: 2026-03-09 07:32:37.762364

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector

# revision identifiers, used by Alembic.
revision: str = 'ce467137221f'
down_revision: Union[str, Sequence[str], None] = '0d8fae5b62a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS vector;')


def downgrade() -> None:
    op.execute('DROP EXTENSION IF EXISTS vector;')