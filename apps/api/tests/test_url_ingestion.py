"""URL ingestion tests — validator SSRF, fetcher redirects/size, HTML
extraction, ingestion. All mocked, no real internet.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, Response

from app.main import app
from app.rag.html_extractor import EmptyHTMLTextError, HTMLTextExtractor
from app.rag.http_fetcher import (
    BadContentTypeError,
    FetchError,
    RedirectLimitError,
    ResponseTooLargeError,
    RobotsBlockedError,
    SecureHTTPFetcher,
)
from app.rag.url_validator import InvalidURLError, UnsafeURLError, URLValidator
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.identity

client = TestClient(app)

PASSWORD = "strong-password-123"
_RUN = uuid.uuid4().hex[:8]


def _email(name: str) -> str:
    return f"{name}-{_RUN}@example.com"


def _slug(name: str) -> str:
    return f"{name}-{_RUN}"


def _register(email: str, full_name: str = "URL Tester"):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": full_name},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _login(email: str) -> str:
    r = client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _setup() -> tuple[str, int, int]:
    email = _email(f"owner{uuid.uuid4().hex[:6]}")
    token = _login(_register(email)["email"])
    r = client.post(
        "/api/v1/organizations",
        json={"name": "Org", "slug": _slug(f"org{uuid.uuid4().hex[:6]}")},
        headers=_auth(token),
    )
    org_id = r.json()["id"]
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots",
        json={"name": "Bot", "slug": _slug(f"bot{uuid.uuid4().hex[:6]}")},
        headers=_auth(token),
    )
    return token, org_id, r.json()["id"]


def _ingest_url(token: str, org_id: int, bot_id: int, url: str, title=None):
    payload = {"url": url}
    if title:
        payload["title"] = title
    return client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/knowledge/documents/url",
        json=payload,
        headers=_auth(token),
    )


# --- Validator / SSRF ---


def test_validator_localhost_blocked() -> None:
    with pytest.raises(UnsafeURLError):
        URLValidator().validate("http://localhost/page")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://0.0.0.0",
        "http://[::1]",
        "http://10.0.0.1",
        "http://172.16.0.1",
        "http://192.168.1.1",
        "http://169.254.169.254/latest/meta-data/",
        "http://[fd00::1]",
    ],
)
def test_validator_unsafe_ips_blocked(url: str) -> None:
    with pytest.raises(UnsafeURLError):
        URLValidator().validate(url)


def test_validator_bad_scheme_blocked() -> None:
    for url in ("file:///etc/passwd", "ftp://example.com/x", "data:text/plain,hi", "javascript:alert(1)"):
        with pytest.raises(InvalidURLError):
            URLValidator().validate(url)


def test_validator_credentials_blocked() -> None:
    with pytest.raises(UnsafeURLError):
        URLValidator().validate("https://user:pass@example.com/x")


def test_validator_arbitrary_port_blocked() -> None:
    with pytest.raises(UnsafeURLError):
        URLValidator().validate("https://example.com:8443/x")


def test_validator_malformed_url() -> None:
    with pytest.raises((InvalidURLError, UnsafeURLError)):
        URLValidator().validate("not a url")


def test_validator_canonicalization() -> None:
    result = URLValidator().validate("HTTPS://Example.COM:443/a/../b?q=1")
    assert result.canonical == "https://example.com/b?q=1"


def test_validator_public_hostname_resolves_ok() -> None:
    result = URLValidator().validate("https://example.com/page")
    assert result.canonical.startswith("https://example.com")


# --- Fetcher ---


class MockTransport:
    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        return self.handler(request)


def _html_response(body: str = "<html><body><p>Hello world</p></body></html>", status=200):
    return Response(status, headers={"content-type": "text/html"}, text=body)


def test_fetcher_safe_redirect_followed() -> None:
    def handler(request):
        if request.url.path == "/start":
            return Response(302, headers={"location": "/final"}, text="")
        return _html_response("<p>Final page</p>")

    fetcher = SecureHTTPFetcher(client=AsyncClient(transport=MockTransport(handler)))
    import asyncio

    canonical, body = asyncio.run(fetcher.fetch_html("https://example.com/start", check_robots=False))
    assert "Final page" in body


def test_fetcher_redirect_limit() -> None:
    def handler(request):
        return Response(302, headers={"location": "/again"}, text="")

    fetcher = SecureHTTPFetcher(client=AsyncClient(transport=MockTransport(handler)))
    import asyncio

    with pytest.raises(RedirectLimitError):
        asyncio.run(fetcher.fetch_html("https://example.com/start", check_robots=False))


def test_fetcher_response_too_large() -> None:
    def handler(request):
        return Response(200, headers={"content-type": "text/html"}, text="x" * (6 * 1024 * 1024))

    fetcher = SecureHTTPFetcher(client=AsyncClient(transport=MockTransport(handler)))
    import asyncio

    with pytest.raises(ResponseTooLargeError):
        asyncio.run(fetcher.fetch_html("https://example.com/", check_robots=False))


def test_fetcher_bad_content_type() -> None:
    def handler(request):
        return Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")

    fetcher = SecureHTTPFetcher(client=AsyncClient(transport=MockTransport(handler)))
    import asyncio

    with pytest.raises(BadContentTypeError):
        asyncio.run(fetcher.fetch_html("https://example.com/doc.pdf", check_robots=False))


def test_fetcher_robots_disallowed() -> None:
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        if request.url.path == "/robots.txt":
            return Response(200, headers={"content-type": "text/plain"}, text="User-agent: *\nDisallow: /private")
        return _html_response()

    fetcher = SecureHTTPFetcher(client=AsyncClient(transport=MockTransport(handler)))
    import asyncio

    with pytest.raises(RobotsBlockedError):
        asyncio.run(fetcher.fetch_html("https://example.com/private/page", check_robots=True))


def test_fetcher_robots_allows_public() -> None:
    def handler(request):
        if request.url.path == "/robots.txt":
            return Response(200, headers={"content-type": "text/plain"}, text="User-agent: *\nDisallow: /private")
        return _html_response("<p>Public</p>")

    fetcher = SecureHTTPFetcher(client=AsyncClient(transport=MockTransport(handler)))
    import asyncio

    _, body = asyncio.run(fetcher.fetch_html("https://example.com/public", check_robots=True))
    assert "Public" in body


# --- HTML extraction ---


def test_html_basic_extraction() -> None:
    assert HTMLTextExtractor().extract("<html><body><p>Hello</p></body></html>") == "Hello"


def test_html_script_removed() -> None:
    out = HTMLTextExtractor().extract("<p>Keep</p><script>alert('x')</script>")
    assert "Keep" in out
    assert "alert" not in out


def test_html_style_removed() -> None:
    out = HTMLTextExtractor().extract("<style>body{color:red}</style><p>Keep</p>")
    assert "Keep" in out
    assert "color" not in out


def test_html_tags_removed() -> None:
    out = HTMLTextExtractor().extract("<div><span>a</span><b>b</b></div>")
    assert "a" in out and "b" in out
    assert "<" not in out


def test_html_entities_decoded() -> None:
    out = HTMLTextExtractor().extract("<p>a &amp; b</p>")
    assert "a & b" in out


def test_html_empty_page_fails() -> None:
    with pytest.raises(EmptyHTMLTextError):
        HTMLTextExtractor().extract("<html><head><title></title></head><body></body></html>")


def test_html_malformed_safe() -> None:
    out = HTMLTextExtractor().extract("<p>unclosed<div>text")
    assert "text" in out


# --- URL ingestion via API (mocked fetcher injection) ---


def _ingest_with_mock(token: str, org_id: int, bot_id: int, url: str, html: str = "<p>URL knowledge content</p>"):
    from app.services.knowledge import KnowledgeService

    import asyncio

    def handler(request):
        if request.url.path == "/robots.txt":
            return Response(200, headers={"content-type": "text/plain"}, text="User-agent: *\nDisallow:")
        return Response(200, headers={"content-type": "text/html"}, text=html)

    fetcher = SecureHTTPFetcher(client=AsyncClient(transport=MockTransport(handler)))
    from app.core.database import get_db
    from tests.conftest import override_get_db

    async def run():
        async with TestSessionLocal() as s:
            service = KnowledgeService(s, fetcher=fetcher)
            return await service.ingest_url(
                org_id,
                bot_id,
                type("P", (), {"url": url, "title": None})(),
            )

    return asyncio.run(run())


def test_url_ingestion_creates_document() -> None:
    token, org_id, bot_id = _setup()
    doc = _ingest_with_mock(token, org_id, bot_id, "https://example.com/page")
    assert doc.source_type == "url"
    assert doc.status == "ready"
    assert doc.source_uri == "https://example.com/page"
    assert doc.content_hash
    r = client.get(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/knowledge/documents/{doc.id}",
        headers=_auth(token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["source_type"] == "url"
    assert body["source_uri"] == "https://example.com/page"
    assert "vector" not in r.text.lower()


def test_url_search_finds_content() -> None:
    token, org_id, bot_id = _setup()
    _ingest_with_mock(token, org_id, bot_id, "https://example.com/k", "<p>unique keyword zebra</p>")
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/knowledge/search",
        json={"query": "unique keyword zebra", "top_k": 5},
        headers=_auth(token),
    )
    assert r.status_code == 200
    assert len(r.json()["results"]) >= 1


def test_url_duplicate_409() -> None:
    token, org_id, bot_id = _setup()
    _ingest_with_mock(token, org_id, bot_id, "https://example.com/dup", "<p>same content here</p>")
    from app.services.knowledge import DuplicateDocumentError, KnowledgeService

    import asyncio

    def handler(request):
        return Response(200, headers={"content-type": "text/html"}, text="<p>same content here</p>")

    fetcher = SecureHTTPFetcher(client=AsyncClient(transport=MockTransport(handler)))

    async def run():
        async with TestSessionLocal() as s:
            service = KnowledgeService(s, fetcher=fetcher)
            with pytest.raises(DuplicateDocumentError):
                await service.ingest_url(
                    org_id, bot_id, type("P", (), {"url": "https://example.com/dup3", "title": None})()
                )

    asyncio.run(run())


def test_cross_org_url_denied() -> None:
    token_a, org_a, bot_a = _setup()
    token_b, org_b, bot_b = _setup()
    r = client.post(
        f"/api/v1/organizations/{org_b}/chatbots/{bot_b}/knowledge/documents/url",
        json={"url": "https://example.com/x"},
        headers=_auth(token_a),
    )
    assert r.status_code == 403


def test_cross_chatbot_isolation() -> None:
    token, org_id, bot_a = _setup()
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots",
        json={"name": "Bot2", "slug": _slug(f"bot2{uuid.uuid4().hex[:6]}")},
        headers=_auth(token),
    )
    bot_b = r.json()["id"]
    doc = _ingest_with_mock(token, org_id, bot_a, "https://example.com/onlya", "<p>only in A secret</p>")
    r2 = client.get(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_b}/knowledge/documents/{doc.id}",
        headers=_auth(token),
    )
    assert r2.status_code == 404
    r3 = client.post(
        f"/api/v1/organizations/{org_id}/chatbots/{bot_b}/knowledge/search",
        json={"query": "only in A secret", "top_k": 5},
        headers=_auth(token),
    )
    assert r3.json()["results"] == []


def test_url_failure_not_searchable() -> None:
    token, org_id, bot_id = _setup()
    from app.services.knowledge import KnowledgeService, URLFetchError

    import asyncio

    def handler(request):
        if request.url.path == "/robots.txt":
            return Response(200, headers={"content-type": "text/plain"}, text="User-agent: *\nDisallow:")
        return Response(500, headers={"content-type": "text/html"}, text="oops")

    fetcher = SecureHTTPFetcher(client=AsyncClient(transport=MockTransport(handler)))

    async def run():
        async with TestSessionLocal() as s:
            service = KnowledgeService(s, fetcher=fetcher)
            with pytest.raises(URLFetchError):
                await service.ingest_url(
                    org_id, bot_id, type("P", (), {"url": "https://example.com/fail", "title": None})()
                )

    asyncio.run(run())
