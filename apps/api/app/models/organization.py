"""Organization ORM model (tenant entity)."""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    # chatbots.organization_id and conversations.organization_id both have
    # ON DELETE CASCADE at the database level (migration 0003; migration 0009
    # for conversations) — passive_deletes=True tells the ORM to trust those
    # constraints instead of loading the collections and nulling the
    # (NOT NULL) foreign keys on delete.
    chatbots: Mapped[list["Chatbot"]] = relationship(
        back_populates="organization", passive_deletes=True
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="organization", passive_deletes=True
    )
