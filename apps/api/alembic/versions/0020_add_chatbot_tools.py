"""add chatbots.tools

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-01

Tool calling (surface-only, no execution): optional per-chatbot list of
tool definitions ({"name", "description", "parameters"}) the model may
request a call against. Nullable, no server_default, no backfill — NULL
keeps today's behavior completely unchanged, same pattern as migration
0019's response_schema.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chatbots", sa.Column("tools", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("chatbots", "tools")
