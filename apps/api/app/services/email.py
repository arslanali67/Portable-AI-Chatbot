"""Resend email delivery — the ONLY place a real network call to Resend
happens. Hand-built httpx call (mirrors the OpenAI-compatible provider
adapter's pattern), not the resend SDK: Resend's send-email endpoint is a
single trivial JSON POST, not complex enough to justify a new dependency.

Local dev/test fallback: when RESEND_API_KEY is empty, send_password_reset_email
logs the reset URL instead of calling Resend (matches this codebase's
established "fake/local by default, real when configured" convention —
see fake AI providers/embeddings). This path is structurally unreachable
in production: fail_fast_production() refuses to even start the app if
RESEND_API_KEY is empty there, so no redundant environment check is needed
here.

Never raises — any Resend failure (network error, invalid key, outage) is
caught and logged (without the API key or the raw reset token) and
reported to the caller as a plain bool, so a delivery failure can never
change the shape of the password-reset-request response (enumeration
safety depends on this).
"""

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("portableai.email")

_RESEND_API_URL = "https://api.resend.com/emails"


class EmailService:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        # Injectable client for tests; otherwise a client built lazily so
        # importing this module never opens a real connection.
        self._client = client

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def send_password_reset_email(self, *, to_email: str, reset_url: str) -> bool:
        """Returns True on successful delivery (or the dev-mode log
        fallback), False on any failure. Never raises."""
        if not settings.resend_api_key:
            # Dev-only fallback — see module docstring. Logging the raw
            # token here is the same deliberate, temporary exception the
            # original log-only stub documented; it never runs in
            # production since the app won't start without a key there.
            logger.info("Password reset requested for %s: %s", to_email, reset_url)
            return True

        payload = {
            "from": settings.email_from_address,
            "to": [to_email],
            "subject": "Reset your PortableAI password",
            "text": (
                "You requested a password reset for your PortableAI account.\n\n"
                f"Reset your password: {reset_url}\n\n"
                "This link expires in 1 hour. If you didn't request this, "
                "you can safely ignore this email."
            ),
        }
        headers = {
            "Authorization": f"Bearer {settings.resend_api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = await self._get_client().post(_RESEND_API_URL, headers=headers, json=payload)
            response.raise_for_status()
            return True
        except Exception:  # noqa: BLE001 - a delivery failure must never propagate
            logger.warning("Password reset email delivery via Resend failed (recipient=%s)", to_email)
            return False
