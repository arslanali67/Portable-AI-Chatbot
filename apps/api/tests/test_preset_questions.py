"""Preset/FAQ questions — save-time validation, canned-response click on
both the public widget and the authenticated conversation, zero AI Gateway
involvement, and the security property that only question_index (never
question/answer text) is ever accepted from a request.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.rate_limit import widget_rate_limiter
from app.main import app
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.identity

client = TestClient(app)

PASSWORD = "Strong-password-123"
_RUN = uuid.uuid4().hex[:8]


def _email(name: str) -> str:
    return f"{name}-{_RUN}-{uuid.uuid4().hex[:6]}@example.com"


def _slug(name: str) -> str:
    return f"{name}-{_RUN}-{uuid.uuid4().hex[:6]}"


def _register(email: str):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "FAQ Tester"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _login(email: str) -> str:
    r = client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_org(token: str) -> int:
    r = client.post("/api/v1/organizations", json={"name": "Org", "slug": _slug("org")}, headers=_auth(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_bot(token: str, org_id: int, **overrides):
    payload = {"name": "Bot", "slug": _slug("bot")}
    payload.update(overrides)
    r = client.post(f"/api/v1/organizations/{org_id}/chatbots", json=payload, headers=_auth(token))
    return r


def _create_conv(token: str, org_id: int, bot_id: int) -> int:
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/conversations",
        json={"title": "Conv"},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _messages(conv_id: int) -> list[tuple[str, str, int]]:
    async with TestSessionLocal() as s:
        r = await s.execute(
            text(
                "SELECT role, content, sequence_number FROM messages "
                "WHERE conversation_id = :cid ORDER BY sequence_number"
            ),
            {"cid": conv_id},
        )
        return [(role, content, seq) for role, content, seq in r.fetchall()]


PRESETS = [
    {"question": "What are your hours?", "answer": "We're open 9-5, Mon-Fri."},
    {"question": "Do you ship internationally?", "answer": "Yes, worldwide."},
]


# --- Save-time validation (ChatbotCreate/Update) ---


def test_preset_questions_too_many_rejected() -> None:
    token = _login(_register(_email("owner"))["email"])
    org_id = _create_org(token)
    r = _create_bot(token, org_id, preset_questions=[{"question": "Q", "answer": "A"} for _ in range(11)])
    assert r.status_code == 422


def test_preset_questions_question_too_long_rejected() -> None:
    token = _login(_register(_email("owner"))["email"])
    org_id = _create_org(token)
    r = _create_bot(token, org_id, preset_questions=[{"question": "Q" * 201, "answer": "A"}])
    assert r.status_code == 422


def test_preset_questions_answer_too_long_rejected() -> None:
    token = _login(_register(_email("owner"))["email"])
    org_id = _create_org(token)
    r = _create_bot(token, org_id, preset_questions=[{"question": "Q", "answer": "A" * 2001}])
    assert r.status_code == 422


def test_preset_questions_valid_accepted() -> None:
    token = _login(_register(_email("owner"))["email"])
    org_id = _create_org(token)
    r = _create_bot(token, org_id, preset_questions=PRESETS)
    assert r.status_code == 201, r.text
    assert r.json()["preset_questions"] == PRESETS


# --- Zero-AI-Gateway-call capture, mirroring test_chat_runtime.py's pattern ---


class CountingFakeProvider:
    def __init__(self, metadata):
        self.metadata = metadata
        self.call_count = 0

    async def generate(self, request, credential_override=None):
        self.call_count += 1
        from app.ai.contracts import AIResponse, AIUsage

        return AIResponse(
            content="[should never be reached by a preset-question click]",
            provider_id=request.provider_id,
            model_id=request.model_id,
            finish_reason="stop",
            usage=AIUsage(input_tokens=1, output_tokens=1),
        )


def _capture_gateway():
    from app.ai.capabilities import AICapability
    from app.ai.metadata import ModelMetadata, ProviderMetadata
    from app.ai.model_registry import ModelRegistry
    from app.ai.provider_registry import ProviderRegistry
    from app.ai.registry import gateway as real_gateway

    capture = CountingFakeProvider(
        ProviderMetadata(
            provider_id="fake-a",
            display_name="A",
            description="",
            enabled=True,
            base_url="",
            authentication_type="none",
            compatibility_type="fake",
            capabilities={AICapability.TEXT_GENERATION},
        )
    )
    providers = ProviderRegistry()
    providers.register(capture)
    models = ModelRegistry()
    models.register(
        ModelMetadata(
            provider_id="fake-a",
            model_id="fake-model-small",
            display_name="s",
            context_window=1000,
            max_output_tokens=100,
            enabled=True,
            capabilities={AICapability.TEXT_GENERATION},
        )
    )
    original_providers, original_models = real_gateway.providers, real_gateway.models
    real_gateway.providers, real_gateway.models = providers, models
    return real_gateway, original_providers, original_models, capture


# --- Authenticated FAQ endpoint ---


def test_authenticated_faq_creates_message_pair_with_stored_text() -> None:
    token = _login(_register(_email("owner"))["email"])
    org_id = _create_org(token)
    bot_id = _create_bot(token, org_id, preset_questions=PRESETS).json()["id"]
    conv_id = _create_conv(token, org_id, bot_id)

    r = client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv_id}/faq",
        json={"question_index": 1},
        headers=_auth(token),
    )
    assert r.status_code == 204, r.text

    import asyncio

    rows = asyncio.run(_messages(conv_id))
    assert rows == [
        ("user", PRESETS[1]["question"], 1),
        ("assistant", PRESETS[1]["answer"], 2),
    ]


def test_authenticated_faq_makes_zero_ai_gateway_calls() -> None:
    gateway, op, om, capture = _capture_gateway()
    try:
        token = _login(_register(_email("owner"))["email"])
        org_id = _create_org(token)
        bot_id = _create_bot(
            token, org_id, provider_id="fake-a", model_id="fake-model-small", preset_questions=PRESETS
        ).json()["id"]
        conv_id = _create_conv(token, org_id, bot_id)

        r = client.post(
            f"/api/v1/organizations/{org_id}/conversations/{conv_id}/faq",
            json={"question_index": 0},
            headers=_auth(token),
        )
        assert r.status_code == 204, r.text
        assert capture.call_count == 0
    finally:
        gateway.providers, gateway.models = op, om


def test_authenticated_faq_out_of_range_index_rejected() -> None:
    token = _login(_register(_email("owner"))["email"])
    org_id = _create_org(token)
    bot_id = _create_bot(token, org_id, preset_questions=PRESETS).json()["id"]
    conv_id = _create_conv(token, org_id, bot_id)

    r = client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv_id}/faq",
        json={"question_index": 5},
        headers=_auth(token),
    )
    assert r.status_code == 422


def test_authenticated_faq_negative_index_rejected_at_schema() -> None:
    token = _login(_register(_email("owner"))["email"])
    org_id = _create_org(token)
    bot_id = _create_bot(token, org_id, preset_questions=PRESETS).json()["id"]
    conv_id = _create_conv(token, org_id, bot_id)

    r = client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv_id}/faq",
        json={"question_index": -1},
        headers=_auth(token),
    )
    assert r.status_code == 422


def test_authenticated_faq_smuggled_text_never_persisted() -> None:
    """Security-critical: a request that also supplies its own question/
    answer text alongside question_index must be rejected outright
    (extra="forbid") — the schema structurally has no field for it to
    reach persistence through in the first place."""
    token = _login(_register(_email("owner"))["email"])
    org_id = _create_org(token)
    bot_id = _create_bot(token, org_id, preset_questions=PRESETS).json()["id"]
    conv_id = _create_conv(token, org_id, bot_id)

    r = client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv_id}/faq",
        json={
            "question_index": 0,
            "question": "SMUGGLED QUESTION",
            "answer": "SMUGGLED ANSWER — never trust me",
        },
        headers=_auth(token),
    )
    assert r.status_code == 422

    import asyncio

    rows = asyncio.run(_messages(conv_id))
    assert rows == []  # nothing persisted from the rejected request


def test_authenticated_faq_archived_conversation_rejected() -> None:
    token = _login(_register(_email("owner"))["email"])
    org_id = _create_org(token)
    bot_id = _create_bot(token, org_id, preset_questions=PRESETS).json()["id"]
    conv_id = _create_conv(token, org_id, bot_id)
    r = client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv_id}/archive", headers=_auth(token)
    )
    assert r.status_code == 200, r.text

    r = client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv_id}/faq",
        json={"question_index": 0},
        headers=_auth(token),
    )
    assert r.status_code == 409


def test_authenticated_faq_not_your_conversation_rejected() -> None:
    owner_token = _login(_register(_email("owner"))["email"])
    org_id = _create_org(owner_token)
    bot_id = _create_bot(owner_token, org_id, preset_questions=PRESETS).json()["id"]
    conv_id = _create_conv(owner_token, org_id, bot_id)

    other_email = _email("other")
    _register(other_email)
    other_token = _login(other_email)
    # other_token's user has no membership in org_id at all.
    r = client.post(
        f"/api/v1/organizations/{org_id}/conversations/{conv_id}/faq",
        json={"question_index": 0},
        headers=_auth(other_token),
    )
    assert r.status_code == 403


# --- Regression: normal authenticated chat still calls the gateway exactly once ---


def test_normal_chat_still_makes_exactly_one_gateway_call_unaffected_by_faq_feature() -> None:
    gateway, op, om, capture = _capture_gateway()
    try:
        token = _login(_register(_email("owner"))["email"])
        org_id = _create_org(token)
        bot_id = _create_bot(
            token, org_id, provider_id="fake-a", model_id="fake-model-small", preset_questions=PRESETS
        ).json()["id"]
        conv_id = _create_conv(token, org_id, bot_id)

        r = client.post(
            f"/api/v1/organizations/{org_id}/conversations/{conv_id}/chat",
            json={"content": "a real question, not a preset click"},
            headers=_auth(token),
        )
        assert r.status_code == 200, r.text
        assert capture.call_count == 1
    finally:
        gateway.providers, gateway.models = op, om


# --- Public widget FAQ endpoint ---


def _setup_public_bot(presets=None):
    email = _email("owner")
    token = _login(_register(email)["email"])
    org_id = _create_org(token)
    payload = {"name": "Public Bot", "slug": _slug("bot"), "welcome_message": "Hi there"}
    if presets is not None:
        payload["preset_questions"] = presets
    r = client.post(f"/api/v1/organizations/{org_id}/chatbots", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    bot_id = r.json()["id"]
    client.post(f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/activate", headers=_auth(token))
    r = client.patch(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}",
        json={"visibility": "public"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/widget-config", headers=_auth(token))
    assert r.status_code == 201, r.text
    return token, org_id, bot_id, r.json()["public_key"]


def _session(public_key: str) -> str:
    r = client.post(
        "/api/v1/public/widget/session",
        json={"public_key": public_key, "origin": "https://example.com"},
    )
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


def test_public_config_exposes_questions_and_answers_eagerly() -> None:
    _, _, _, key = _setup_public_bot(PRESETS)
    r = client.get("/api/v1/public/widget/config", params={"public_key": key})
    assert r.status_code == 200
    assert r.json()["preset_questions"] == PRESETS


def test_public_faq_creates_conversation_when_session_has_none() -> None:
    _, _, _, key = _setup_public_bot(PRESETS)
    sess = _session(key)

    r = client.post(
        "/api/v1/public/widget/faq",
        json={"session_token": sess, "question_index": 0, "origin": "https://example.com"},
    )
    assert r.status_code == 204, r.text

    import asyncio
    from sqlalchemy import text as sa_text

    async def _find_conv_for_session():
        async with TestSessionLocal() as s:
            r = await s.execute(
                sa_text("SELECT conversation_id FROM widget_sessions WHERE session_token = :t"),
                {"t": sess},
            )
            return r.scalar_one()

    conv_id = asyncio.run(_find_conv_for_session())
    assert conv_id is not None
    rows = asyncio.run(_messages(conv_id))
    assert rows == [
        ("user", PRESETS[0]["question"], 1),
        ("assistant", PRESETS[0]["answer"], 2),
    ]


def test_public_faq_makes_zero_ai_gateway_calls() -> None:
    gateway, op, om, capture = _capture_gateway()
    try:
        _, _, _, key = _setup_public_bot(PRESETS)
        sess = _session(key)
        r = client.post(
            "/api/v1/public/widget/faq",
            json={"session_token": sess, "question_index": 0, "origin": "https://example.com"},
        )
        assert r.status_code == 204, r.text
        assert capture.call_count == 0
    finally:
        gateway.providers, gateway.models = op, om


def test_public_faq_out_of_range_index_rejected() -> None:
    _, _, _, key = _setup_public_bot(PRESETS)
    sess = _session(key)
    r = client.post(
        "/api/v1/public/widget/faq",
        json={"session_token": sess, "question_index": 99, "origin": "https://example.com"},
    )
    assert r.status_code == 422


def test_public_faq_smuggled_text_never_persisted() -> None:
    _, _, _, key = _setup_public_bot(PRESETS)
    sess = _session(key)
    r = client.post(
        "/api/v1/public/widget/faq",
        json={
            "session_token": sess,
            "question_index": 0,
            "origin": "https://example.com",
            "question": "SMUGGLED",
            "answer": "SMUGGLED ANSWER",
        },
    )
    assert r.status_code == 422


def test_public_faq_invalid_session_rejected() -> None:
    r = client.post(
        "/api/v1/public/widget/faq",
        json={"session_token": "not-a-real-session", "question_index": 0},
    )
    assert r.status_code == 403


def test_public_faq_rate_limited() -> None:
    _, _, _, key = _setup_public_bot(PRESETS)
    sess = _session(key)
    for _ in range(30):
        widget_rate_limiter.allow(f"session:{sess}")
    r = client.post(
        "/api/v1/public/widget/faq",
        json={"session_token": sess, "question_index": 0, "origin": "https://example.com"},
    )
    assert r.status_code == 429
