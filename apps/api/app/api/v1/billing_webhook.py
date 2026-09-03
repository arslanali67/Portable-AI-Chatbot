"""Stripe webhook endpoint — entirely outside normal JWT auth (Stripe
cannot send a bearer token). The ONLY trust boundary is the cryptographic
signature check, which runs BEFORE any parsing or business logic — a
missing/invalid signature is rejected immediately, no DB access.

This is a materially different threat model from the public widget's
boundary (which trusts a server-derived public_key/session plus rate
limiting/origin checks) — here there is no session or per-request
identity at all, only Stripe's HMAC signature over the raw request body.
"""

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.stripe_client import verify_webhook_signature
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.services.billing import BillingService

router = APIRouter(prefix="/billing", tags=["billing-webhook"])
logger = get_logger("portableai.billing_webhook")


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    # Raw bytes, exactly as sent — Stripe's signature is computed over this
    # exact payload. No Pydantic body model is declared on this route: that
    # would make FastAPI parse JSON before we can verify the signature.
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    if sig_header is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing signature")

    try:
        event = verify_webhook_signature(payload, sig_header, settings.stripe_webhook_secret)
    except stripe.SignatureVerificationError:
        logger.warning("Stripe webhook signature verification failed")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

    # construct_event() returns a stripe.Event object (attribute/item
    # access only, no .get()) — BillingService works with plain dicts.
    await BillingService(db).handle_webhook_event(event.to_dict())
    return {"received": True}
