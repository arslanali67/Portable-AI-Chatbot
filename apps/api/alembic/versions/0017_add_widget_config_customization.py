"""add widget_configs.theme_color, widget_position, avatar_url

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-31

Widget-presentation-layer customization fields. All nullable, no
server_default and no backfill — NULL means "use widget.js's built-in
default" (today's hardcoded blue, bottom-right, no avatar), same pattern
as migration 0015's per-chatbot RAG config. avatar_url stores a
server-generated, root-relative served path (e.g. /widget-avatars/<uuid>.png)
written only by the avatar-upload endpoint — never a client-supplied value.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column on an EXISTING table does not implicitly CREATE TYPE the
    # way op.create_table does for a brand-new table — the enum type must be
    # created explicitly first (see migration 0003 for the create-table case).
    widget_position = sa.Enum("bottom_right", "bottom_left", name="widget_position")
    widget_position.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "widget_configs", sa.Column("theme_color", sa.String(length=7), nullable=True)
    )
    op.add_column(
        "widget_configs", sa.Column("widget_position", widget_position, nullable=True)
    )
    op.add_column(
        "widget_configs", sa.Column("avatar_url", sa.String(length=255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("widget_configs", "avatar_url")
    op.drop_column("widget_configs", "widget_position")
    op.drop_column("widget_configs", "theme_color")
    op.execute("DROP TYPE IF EXISTS widget_position")
