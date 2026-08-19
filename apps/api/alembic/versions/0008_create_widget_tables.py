"""create widget_configs, widget_sessions

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-18

Public embeddable widget: per-chatbot public_key config + anonymous sessions.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "widget_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "chatbot_id",
            sa.Integer(),
            sa.ForeignKey("chatbots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("public_key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("allowed_origins", sa.JSON(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("public_key", name="uq_widget_configs_public_key"),
    )
    op.create_index("ix_widget_configs_public_key", "widget_configs", ["public_key"])
    op.create_index("ix_widget_configs_chatbot_id", "widget_configs", ["chatbot_id"])

    op.create_table(
        "widget_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "chatbot_id",
            sa.Integer(),
            sa.ForeignKey("chatbots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_token", sa.String(length=64), nullable=False),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_token", name="uq_widget_sessions_session_token"),
    )
    op.create_index("ix_widget_sessions_session_token", "widget_sessions", ["session_token"])
    op.create_index("ix_widget_sessions_chatbot_id", "widget_sessions", ["chatbot_id"])


def downgrade() -> None:
    op.drop_index("ix_widget_sessions_chatbot_id", table_name="widget_sessions")
    op.drop_index("ix_widget_sessions_session_token", table_name="widget_sessions")
    op.drop_table("widget_sessions")
    op.drop_index("ix_widget_configs_chatbot_id", table_name="widget_configs")
    op.drop_index("ix_widget_configs_public_key", table_name="widget_configs")
    op.drop_table("widget_configs")
