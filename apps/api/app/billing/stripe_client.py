"""Thin wrapper around the stripe SDK — the ONLY place real Stripe API
calls happen. BillingService depends on this exact shape; tests inject a
fake implementing the same three methods instead of touching the network.
Signature verification is a free function since it needs no API key —
it's pure local HMAC verification against the webhook signing secret.
"""

from typing import Any

import stripe


class StripeClient:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def create_checkout_session(
        self,
        *,
        customer_id: str | None,
        customer_email: str | None,
        price_id: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
    ) -> str:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            customer_email=None if customer_id else customer_email,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata,
            api_key=self._api_key,
        )
        return session["url"]

    def list_invoices(self, *, customer_id: str) -> list[dict[str, Any]]:
        invoices = stripe.Invoice.list(customer=customer_id, api_key=self._api_key)
        return list(invoices["data"])


def verify_webhook_signature(payload: bytes, sig_header: str, webhook_secret: str) -> dict[str, Any]:
    """Raises stripe.SignatureVerificationError on a missing/invalid
    signature — callers must reject before any parsing/business logic."""
    return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
