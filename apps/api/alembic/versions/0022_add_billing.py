"""add subscriptions, stripe_credential

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-03

Billing (Stripe, flat tiers): subscriptions is one row per organization
that has ever touched billing (Checkout or a platform-admin manual
override) — no row means Free tier, always active. stripe_credential is
a single-row (id=1) table holding the platform-wide Fernet-encrypted
Stripe secret key. Neither table is backfilled — this migration creates
zero rows, so no existing organization is affected.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tier", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_subscriptions_organization_id", "subscriptions", ["organization_id"], unique=True
    )

    op.create_table(
        "stripe_credential",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("encrypted_secret_key", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_table("stripe_credential")
    op.drop_index("ix_subscriptions_organization_id", table_name="subscriptions")
    op.drop_table("subscriptions")
