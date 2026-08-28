"""conversations FKs: RESTRICT -> CASCADE

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-28

Migration 0005 intentionally used RESTRICT on conversations.organization_id,
conversations.chatbot_id, and conversations.user_id ("no accidental history
loss"). Per architecture.md Step 10 (Deletion Strategy), deleting a chatbot
is meant to cascade its dependent data — including conversations/messages —
via database-level ON DELETE CASCADE, and the same cascade is required when
deleting an organization. This migration supersedes 0005's RESTRICT choice
to align the schema with that documented deletion strategy.

users.id keeps its own FK (conversations.user_id) unchanged in cascade
semantics relative to chatbot/organization deletion — only the three named
constraints below are altered; no other table/constraint is touched.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "conversations_organization_id_fkey", "conversations", type_="foreignkey"
    )
    op.create_foreign_key(
        "conversations_organization_id_fkey",
        "conversations",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("conversations_chatbot_id_fkey", "conversations", type_="foreignkey")
    op.create_foreign_key(
        "conversations_chatbot_id_fkey",
        "conversations",
        "chatbots",
        ["chatbot_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("conversations_user_id_fkey", "conversations", type_="foreignkey")
    op.create_foreign_key(
        "conversations_user_id_fkey",
        "conversations",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("conversations_user_id_fkey", "conversations", type_="foreignkey")
    op.create_foreign_key(
        "conversations_user_id_fkey",
        "conversations",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint("conversations_chatbot_id_fkey", "conversations", type_="foreignkey")
    op.create_foreign_key(
        "conversations_chatbot_id_fkey",
        "conversations",
        "chatbots",
        ["chatbot_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        "conversations_organization_id_fkey", "conversations", type_="foreignkey"
    )
    op.create_foreign_key(
        "conversations_organization_id_fkey",
        "conversations",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
