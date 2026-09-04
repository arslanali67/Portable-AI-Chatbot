"""add chatbots.preset_questions

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-04

Preset/FAQ questions: optional per-chatbot list of admin-authored
{"question", "answer"} pairs, suggested to visitors/users as clickable
canned-response chips. Nullable, no server_default, no backfill — NULL
keeps today's behavior completely unchanged, same pattern as migrations
0019 (response_schema) and 0020 (tools).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chatbots", sa.Column("preset_questions", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("chatbots", "preset_questions")
