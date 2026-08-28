"""create ai_provider_overrides, ai_model_overrides

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-28

Thin, platform-admin-mutable override tables layered on top of the
code-owned provider/model registries (app/ai/registry.py). No provider/
model metadata is duplicated here — only the one fact the registry can't
express: whether a platform admin has disabled something the registry
otherwise considers enabled. See architecture.md Step 15 "Platform Admin
Mutation". disabled_by uses ON DELETE SET NULL (not CASCADE) so that if
the admin user who disabled something is ever removed, the override
stays in effect — losing attribution is acceptable, silently
re-enabling a deliberately-disabled provider/model is not.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_provider_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.String(length=100), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "disabled_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.UniqueConstraint("provider_id", name="uq_ai_provider_overrides_provider_id"),
    )
    op.create_index(
        "ix_ai_provider_overrides_provider_id", "ai_provider_overrides", ["provider_id"]
    )

    op.create_table(
        "ai_model_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "disabled_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
            "provider_id", "model_id", name="uq_ai_model_overrides_provider_model"
        ),
    )
    op.create_index(
        "ix_ai_model_overrides_provider_id", "ai_model_overrides", ["provider_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_ai_model_overrides_provider_id", table_name="ai_model_overrides")
    op.drop_table("ai_model_overrides")
    op.drop_index("ix_ai_provider_overrides_provider_id", table_name="ai_provider_overrides")
    op.drop_table("ai_provider_overrides")
