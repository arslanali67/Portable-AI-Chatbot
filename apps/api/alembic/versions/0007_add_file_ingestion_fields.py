"""add file ingestion fields to knowledge_documents

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-18

Adds original_filename, file_size, content_hash for file ingestion + dedup.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column("original_filename", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("file_size", sa.Integer(), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("content_hash", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_knowledge_documents_content_hash", "knowledge_documents", ["content_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_documents_content_hash", table_name="knowledge_documents")
    op.drop_column("knowledge_documents", "content_hash")
    op.drop_column("knowledge_documents", "file_size")
    op.drop_column("knowledge_documents", "original_filename")
