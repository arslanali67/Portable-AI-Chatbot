"""create ai_provider_credentials

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-01

BYOK (bring-your-own-key): organization-scoped, Fernet-encrypted AI
provider API keys. `provider_id` matches the code registry's provider_id
but is a plain string, not a DB FK — providers stay code-registered.
Unique on (organization_id, provider_id). `encrypted_key` stores Fernet
ciphertext, never plaintext. `updated_by` uses ON DELETE SET NULL (not
CASCADE), matching migration 0012's ai_provider_overrides.disabled_by
precedent — losing attribution on user deletion is acceptable, silently
dropping the credential is not.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_provider_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_id", sa.String(length=100), nullable=False),
        sa.Column("encrypted_key", sa.LargeBinary(), nullable=False),
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
        sa.Column(
            "updated_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "organization_id", "provider_id", name="uq_ai_provider_credentials_org_provider"
        ),
    )
    op.create_index(
        "ix_ai_provider_credentials_organization_id",
        "ai_provider_credentials",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_provider_credentials_organization_id", table_name="ai_provider_credentials"
    )
    op.drop_table("ai_provider_credentials")
