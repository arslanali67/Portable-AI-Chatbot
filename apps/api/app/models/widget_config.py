"""Widget configuration ORM model — public embed credential per chatbot."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import WidgetPosition


def _enum_values(enum_cls):
    """Store enum values (lowercase) in the database, not member names."""
    return [member.value for member in enum_cls]


class WidgetConfig(Base):
    __tablename__ = "widget_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    chatbot_id: Mapped[int] = mapped_column(
        ForeignKey("chatbots.id", ondelete="CASCADE"), index=True, nullable=False
    )
    public_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # enabled is assigned at the service layer (WidgetConfigService.create always
    # sets it explicitly; there is no other insertion path). No server_default is
    # added deliberately — an implicit DB default could silently enable a widget
    # inserted outside the service. Migration 0008 keeps the column default-less
    # and NOT NULL.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allowed_origins: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    # Widget-presentation customization. All nullable, no server_default, no
    # backfill: NULL means "use widget.js's built-in default" (today's
    # hardcoded blue, bottom-right, no avatar) — same pattern as the
    # per-chatbot rag_enabled/rag_top_k NULL semantics.
    theme_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    widget_position: Mapped[WidgetPosition | None] = mapped_column(
        Enum(WidgetPosition, name="widget_position", values_callable=_enum_values),
        nullable=True,
    )
    # Server-generated, root-relative served path (e.g. /widget-avatars/<uuid>.png)
    # written only by the avatar-upload endpoint — never a client-supplied value.
    avatar_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    chatbot: Mapped["Chatbot"] = relationship()
