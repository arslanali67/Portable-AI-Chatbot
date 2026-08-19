"""create chatbots

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-17

Creates the organization-owned chatbot configuration table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    chatbot_status = sa.Enum("draft", "active", "archived", name="chatbot_status")
    chatbot_visibility = sa.Enum("private", "public", name="chatbot_visibility")

    op.create_table(
        "chatbots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("welcome_message", sa.Text(), nullable=False),
        sa.Column("status", chatbot_status, nullable=False),
        sa.Column("visibility", chatbot_visibility, nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "organization_id", "slug", name="uq_chatbots_organization_slug"
        ),
    )
    op.create_index("ix_chatbots_organization_id", "chatbots", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_chatbots_organization_id", table_name="chatbots")
    op.drop_table("chatbots")
    op.execute("DROP TYPE IF EXISTS chatbot_status")
    op.execute("DROP TYPE IF EXISTS chatbot_visibility")
