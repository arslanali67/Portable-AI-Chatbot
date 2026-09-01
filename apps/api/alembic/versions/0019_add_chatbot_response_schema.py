"""add chatbots.response_schema

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-01

Structured output: optional per-chatbot JSON schema used to request and
validate schema-conformant model responses. Nullable, no server_default,
no backfill — NULL keeps today's free-text behavior completely unchanged,
same pattern as migration 0015's per-chatbot RAG config.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chatbots", sa.Column("response_schema", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("chatbots", "response_schema")
