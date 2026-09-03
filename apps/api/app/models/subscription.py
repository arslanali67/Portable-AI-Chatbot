"""Subscription — per-organization billing state (Stripe-backed).

No row for an organization means Free tier, always active, never touched
by billing logic. A row exists only once an organization's owner starts a
real Stripe Checkout flow, or a platform admin manually assigns a tier.
See architecture.md §8b.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    tier: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Stripe's own status vocabulary (active/past_due/canceled/incomplete/
    # unpaid/...) — stored verbatim, never re-interpreted into a new enum.
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
