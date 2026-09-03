"""add organizations.disabled_at/disabled_message

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-03

Platform-owner dashboard: reversible disable/enable toggle for an
organization. Both columns nullable, no server_default, no backfill —
existing organizations stay NULL (enabled), same pattern as prior
optional-field migrations (0019, 0020).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organizations", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("disabled_message", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("organizations", "disabled_message")
    op.drop_column("organizations", "disabled_at")
