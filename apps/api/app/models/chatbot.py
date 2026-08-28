"""Chatbot ORM model — organization-owned, provider-agnostic configuration."""

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ChatbotStatus, ChatbotVisibility


def _enum_values(enum_cls):
    """Store enum values (lowercase) in the database, not member names."""
    return [member.value for member in enum_cls]


class Chatbot(Base):
    __tablename__ = "chatbots"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_chatbots_organization_slug"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    welcome_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[ChatbotStatus] = mapped_column(
        Enum(ChatbotStatus, name="chatbot_status", values_callable=_enum_values),
        default=ChatbotStatus.DRAFT,
        nullable=False,
    )
    visibility: Mapped[ChatbotVisibility] = mapped_column(
        Enum(ChatbotVisibility, name="chatbot_visibility", values_callable=_enum_values),
        default=ChatbotVisibility.PRIVATE,
        nullable=False,
    )
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    provider_id: Mapped[str] = mapped_column(String(100), default="fake-a", nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), default="fake-model-small", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship(back_populates="chatbots")
    # conversations.chatbot_id has ON DELETE CASCADE at the database level
    # (migration 0009) — passive_deletes=True tells the ORM to trust that
    # constraint instead of loading the collection and nulling the
    # (NOT NULL) foreign key on delete.
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="chatbot", passive_deletes=True
    )
