"""EmailService (Resend) unit tests — all HTTP is mocked, no network, no
real API key required. Mirrors test_openai_provider.py's MockTransport
pattern.
"""

import asyncio
import contextlib
import json

import httpx
from httpx import AsyncClient, Request, Response

from app.core.config import settings
from app.services.email import EmailService


class MockTransport:
    def __init__(self, response: Response | None = None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.requests: list[Request] = []

    async def handle_async_request(self, request: Request) -> Response:
        self.requests.append(request)
        if self._error:
            raise self._error
        return self._response


def _run(coro):
    return asyncio.run(coro)


@contextlib.contextmanager
def _patch_resend_settings(api_key: str, from_address: str = "onboarding@resend.dev"):
    original_key = settings.resend_api_key
    original_from = settings.email_from_address
    settings.resend_api_key = api_key
    settings.email_from_address = from_address
    try:
        yield
    finally:
        settings.resend_api_key = original_key
        settings.email_from_address = original_from


def _ok_response():
    return Response(200, json={"id": "email_abc123"})


# --- dev fallback: no key configured ---


def test_no_api_key_falls_back_to_log_and_reports_success() -> None:
    with _patch_resend_settings(""):
        service = EmailService()
        result = _run(
            service.send_password_reset_email(
                to_email="user@example.com", reset_url="https://app.example.com/reset?token=RAWTOKEN123"
            )
        )
    assert result is True


def test_no_api_key_never_attempts_a_network_call() -> None:
    transport = MockTransport(_ok_response())
    with _patch_resend_settings(""):
        service = EmailService(client=AsyncClient(transport=transport))
        _run(service.send_password_reset_email(to_email="user@example.com", reset_url="https://x/reset?token=T"))
    assert transport.requests == []  # never even attempted, dev fallback short-circuits first


# --- real Resend call: success ---


def test_configured_key_sends_via_resend_with_correct_payload() -> None:
    transport = MockTransport(_ok_response())
    with _patch_resend_settings("re_test_fake_key_do_not_use", from_address="test@example.com"):
        service = EmailService(client=AsyncClient(transport=transport))
        result = _run(
            service.send_password_reset_email(
                to_email="recipient@example.com", reset_url="https://app.example.com/reset?token=RAWTOKEN123"
            )
        )
    assert result is True
    assert len(transport.requests) == 1
    req = transport.requests[0]
    assert str(req.url) == "https://api.resend.com/emails"
    assert req.headers["authorization"] == "Bearer re_test_fake_key_do_not_use"
    body = json.loads(req.content)
    assert body["from"] == "test@example.com"
    assert body["to"] == ["recipient@example.com"]
    assert "RAWTOKEN123" in body["text"]


# --- real Resend call: failure (network error, bad status) ---


def test_resend_network_error_returns_false_never_raises() -> None:
    transport = MockTransport(error=httpx.ConnectError("connection refused"))
    with _patch_resend_settings("re_test_fake_key_do_not_use"):
        service = EmailService(client=AsyncClient(transport=transport))
        result = _run(
            service.send_password_reset_email(to_email="user@example.com", reset_url="https://x/reset?token=SECRETTOKEN")
        )
    assert result is False


def test_resend_error_status_returns_false_never_raises() -> None:
    transport = MockTransport(Response(401, json={"message": "invalid API key"}))
    with _patch_resend_settings("re_test_fake_key_do_not_use"):
        service = EmailService(client=AsyncClient(transport=transport))
        result = _run(
            service.send_password_reset_email(to_email="user@example.com", reset_url="https://x/reset?token=SECRETTOKEN")
        )
    assert result is False


def test_resend_failure_never_logs_api_key_or_raw_token(caplog) -> None:
    transport = MockTransport(error=httpx.ConnectError("connection refused"))
    fake_key = "re_super_secret_fake_key_zzz999"
    raw_token = "ULTRASECRETRAWTOKENVALUE"
    with _patch_resend_settings(fake_key):
        service = EmailService(client=AsyncClient(transport=transport))
        with caplog.at_level("DEBUG", logger="portableai.email"):
            _run(
                service.send_password_reset_email(
                    to_email="user@example.com", reset_url=f"https://x/reset?token={raw_token}"
                )
            )
    assert fake_key not in caplog.text
    assert raw_token not in caplog.text
