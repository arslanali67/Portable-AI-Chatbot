"""add hnsw index on document_chunks.vector

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-28

RetrievalService/ChunkRepository.search always queries via cosine distance
(DocumentChunk.vector.cosine_distance(...)), so the index uses the matching
vector_cosine_ops operator class.

HNSW over IVFFlat: pgvector 0.8.6 (verified live) comfortably exceeds
HNSW's >=0.5.0 requirement. IVFFlat requires a `lists` parameter tuned to
the expected row count and needs representative data present at build
time to train well-formed clusters — but this repo's CI (.github/workflows
/ci.yml) provisions a brand-new database and runs `alembic upgrade head`
before any row exists, so an IVFFlat index would always be built against
zero rows. HNSW has no such data dependency; it builds/tunes incrementally
as rows are inserted, using pgvector's documented defaults (m=16,
ef_construction=64), which are appropriate at the current and
near-term expected scale.

Not CONCURRENTLY: every migration in this repo runs inside a single
transaction (see alembic/env.py's do_run_migrations, which always wraps
in context.begin_transaction()), and CREATE INDEX CONCURRENTLY cannot run
inside a transaction block. No prior migration in this repo uses
op.get_context().autocommit_block() to opt out of that, so a regular
CREATE INDEX is used here to stay consistent with the existing migration
pattern. This project's deployment model (architecture.md Step 31) also
runs migrations via a one-shot api-migrate service before the API accepts
traffic, so a brief exclusive lock during index creation is not a
concern for the traffic patterns this repo currently targets.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_document_chunks_vector_hnsw_cosine"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "document_chunks",
        ["vector"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"vector": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="document_chunks")
