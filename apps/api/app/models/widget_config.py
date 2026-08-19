"""Widget configuration ORM model — public embed credential per chatbot."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


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
