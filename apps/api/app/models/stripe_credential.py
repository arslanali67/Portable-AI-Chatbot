"""StripeCredential — the platform-wide Stripe secret API key.

A single-row table (id is always 1), Fernet-encrypted, mirroring
ai_provider_credentials' encrypt-on-write/decrypt-just-in-time pattern —
but platform-wide, not per-organization. See architecture.md §8b.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StripeCredential(Base):
    __tablename__ = "stripe_credential"

    id: Mapped[int] = mapped_column(primary_key=True)
    encrypted_secret_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
