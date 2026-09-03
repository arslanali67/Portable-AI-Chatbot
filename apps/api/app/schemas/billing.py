"""Billing schemas — Stripe checkout, subscription status, invoices, and
the platform-wide Stripe credential (write-only, masked, mirrors BYOK)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: str = Field(..., min_length=1)


class CheckoutResponse(BaseModel):
    checkout_url: str


class SubscriptionResponse(BaseModel):
    tier: str | None
    status: str | None
    current_period_end: datetime | None


class InvoiceResponse(BaseModel):
    id: str
    created: datetime
    amount_paid: int
    currency: str
    status: str
    hosted_invoice_url: str | None


class InvoiceListResponse(BaseModel):
    items: list[InvoiceResponse]


class StripeCredentialSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret_key: str = Field(..., min_length=1)


class StripeCredentialStatusResponse(BaseModel):
    masked_key: str
    updated_at: datetime
    updated_by_email: str | None


class SubscriptionOverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: str | None = None
    status: str | None = None
