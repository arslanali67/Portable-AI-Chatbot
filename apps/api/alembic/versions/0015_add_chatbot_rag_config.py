"""add chatbots.rag_enabled, chatbots.rag_top_k

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-31

Per-chatbot RAG configuration. rag_enabled (NOT NULL, server_default true —
existing rows keep today's always-on retrieval behavior unchanged) lets a
chatbot skip RetrievalService entirely. rag_top_k is nullable with no
backfill: NULL means "use the global settings.rag_top_k default", not a
separate sentinel value, so existing chatbots stay on the platform default
until an operator opts them into an explicit override.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chatbots",
        sa.Column("rag_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "chatbots",
        sa.Column("rag_top_k", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chatbots", "rag_top_k")
    op.drop_column("chatbots", "rag_enabled")
