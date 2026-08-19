"""add chatbot AI configuration (provider_id, model_id)

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-17

Adds provider/model string columns to chatbots. No enums — extensible ids.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chatbots",
        sa.Column("provider_id", sa.String(length=100), nullable=False, server_default="fake-a"),
    )
    op.add_column(
        "chatbots",
        sa.Column(
            "model_id", sa.String(length=100), nullable=False, server_default="fake-model-small"
        ),
    )


def downgrade() -> None:
    op.drop_column("chatbots", "model_id")
    op.drop_column("chatbots", "provider_id")
