"""add users.is_platform_admin

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-28

Platform-level, non-tenant-scoped administration flag — orthogonal to
MembershipRole. Grants no access to any organization's tenant-scoped
data; only gates the new AI provider/model override mutation endpoints
(migration 0012). No self-service promotion path exists anywhere in the
API — this column is set only via direct DB access. server_default is
required (not just an ORM-level default) because ADD COLUMN ... NOT NULL
against an already-populated users table needs a default for existing
rows (same pattern as migration 0004's chatbots.provider_id/model_id).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_platform_admin")
