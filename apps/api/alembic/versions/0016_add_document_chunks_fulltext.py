"""add document_chunks.content_tsv (full-text search) + GIN index

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-31

Adds a generated tsvector column over document_chunks.content plus a GIN
index, enabling hybrid search: ChunkRepository/RetrievalService combine
this full-text signal with the existing HNSW cosine-similarity search via
Reciprocal Rank Fusion (see architecture.md's Similarity Search section).

GENERATED ALWAYS AS ... STORED is computed by Postgres for every existing
row as part of this ALTER TABLE — no separate backfill step is needed or
possible (Postgres owns the column's value; it cannot be written directly).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_document_chunks_content_tsv_gin"


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column(
            "content_tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', content)", persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        INDEX_NAME,
        "document_chunks",
        ["content_tsv"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="document_chunks")
    op.drop_column("document_chunks", "content_tsv")
