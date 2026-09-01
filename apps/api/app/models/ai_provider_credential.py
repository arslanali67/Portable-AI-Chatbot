"""BYOK AI provider credential — organization-scoped, Fernet-encrypted API key.

Optional per (organization, provider_id); provider_id matches the code
registry's provider_id but is a plain string, not a DB FK — providers stay
code-registered. See architecture.md "Credential Isolation".
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AIProviderCredential(Base):
    __tablename__ = "ai_provider_credentials"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "provider_id", name="uq_ai_provider_credentials_org_provider"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider_id: Mapped[str] = mapped_column(String(100), nullable=False)
    encrypted_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
