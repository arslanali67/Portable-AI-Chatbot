"""Bounded same-domain crawl ingestion tests — all mocked, no real internet.

Uses a NoDNSURLValidator test double (same scheme/port/credential/literal-IP
checks as the real URLValidator, but no real DNS resolution) so made-up
subdomains (blog.example.com, foo.github.io, ...) work without needing real
DNS records for them. A literal private IP, or a hostname explicitly listed
as unsafe, is still rejected exactly like the real validator would reject it
- that's what the SSRF test below relies on.
"""

import asyncio
import ipaddress
import uuid
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, Response

from app.core.config import settings
from app.main import app
from app.rag.http_fetcher import SecureHTTPFetcher
from app.rag.url_validator import InvalidURLError, UnsafeURLError, URLValidator, ValidatedURL, _is_unsafe_ip
from app.services.knowledge import CrawlResult, KnowledgeService
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.identity

client = TestClient(app)

PASSWORD = "Strong-password-123"
_RUN = uuid.uuid4().hex[:8]


def _email(name: str) -> str:
    return f"{name}-{_RUN}-{uuid.uuid4().hex[:6]}@example.com"


def _slug(name: str) -> str:
    return f"{name}-{_RUN}-{uuid.uuid4().hex[:6]}"


def _setup() -> tuple[str, int, int]:
    email = _email("owner")
    r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD, "full_name": "Crawl Tester"})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/v1/organizations", json={"name": "Org", "slug": _slug("org")}, headers=headers)
    org_id = r.json()["id"]
    r = client.post(
        f"/api/v1/organizations/{org_id}/chatbots", json={"name": "Bot", "slug": _slug("bot")}, headers=headers
    )
    return token, org_id, r.json()["id"]


class NoDNSURLValidator:
    """Test double for URLValidator: identical scheme/port/credential/
    literal-IP checks, but skips real DNS resolution for non-IP hostnames.
    `unsafe_hostnames` simulates "this hostname resolves to a private IP"
    for SSRF testing without needing a real DNS rebinding setup."""

    def __init__(self, unsafe_hostnames: frozenset[str] = frozenset()) -> None:
        self._unsafe_hostnames = unsafe_hostnames

    def validate(self, url: str) -> ValidatedURL:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise InvalidURLError("scheme not allowed")
        if not parsed.hostname:
            raise InvalidURLError("missing hostname")
        if parsed.username or parsed.password:
            raise UnsafeURLError("credentials in URL are not allowed")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in (80, 443):
            raise UnsafeURLError("port not allowed")
        hostname = parsed.hostname.lower()
        try:
            ip = ipaddress.ip_address(hostname)
            if _is_unsafe_ip(str(ip)):
                raise UnsafeURLError("unsafe IP address")
        except ValueError:
            if hostname == "localhost" or hostname in self._unsafe_hostnames:
                raise UnsafeURLError("unsafe hostname")
        return ValidatedURL(
            canonical=URLValidator._canonicalize(parsed, hostname, port), hostname=hostname, port=port
        )


class MockTransport:
    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        return await self.handler(request)


def _site(
    pages: dict[str, dict[str, str]],
    *,
    robots: dict[str, str] | None = None,
    robots_calls: dict[str, int] | None = None,
    delay_seconds: float = 0.0,
):
    """pages: {host: {path: html}}. robots: {host: body} (default allow-all).
    robots_calls, if given, counts robots.txt fetches per host."""
    robots = robots or {}

    async def handler(request):
        if delay_seconds:
            await asyncio.sleep(delay_seconds)
        host = request.url.host
        path = request.url.path
        if path == "/robots.txt":
            if robots_calls is not None:
                robots_calls[host] = robots_calls.get(host, 0) + 1
            return Response(200, headers={"content-type": "text/plain"}, text=robots.get(host, "User-agent: *\nDisallow:"))
        html = pages.get(host, {}).get(path)
        if html is None:
            return Response(404, headers={"content-type": "text/html"}, text="not found")
        return Response(200, headers={"content-type": "text/html"}, text=html)

    return handler


def _crawl_with_mock(
    org_id: int, bot_id: int, url: str, *, handler, title: str | None = None, unsafe_hostnames: frozenset[str] = frozenset()
) -> tuple[CrawlResult, MockTransport]:
    transport = MockTransport(handler)
    fetcher = SecureHTTPFetcher(
        client=AsyncClient(transport=transport), validator=NoDNSURLValidator(unsafe_hostnames)
    )

    async def run():
        async with TestSessionLocal() as s:
            service = KnowledgeService(s, fetcher=fetcher)
            return await service.crawl(org_id, bot_id, type("P", (), {"url": url, "title": title})())

    return asyncio.run(run()), transport


async def _document_ids_for_chatbot(bot_id: int) -> list[int]:
    from sqlalchemy import select

    from app.models import KnowledgeDocument

    async with TestSessionLocal() as s:
        result = await s.execute(select(KnowledgeDocument).where(KnowledgeDocument.chatbot_id == bot_id))
        return [d.id for d in result.scalars().all()]


# --- Multi-page crawl, metadata ---


def test_crawl_multi_page_creates_documents_with_metadata() -> None:
    _, org_id, bot_id = _setup()
    handler = _site(
        {
            "example.com": {
                "/": '<p>Entry page</p><a href="/a">A</a><a href="/b">B</a>',
                "/a": "<p>Page A unique content alpha</p>",
                "/b": "<p>Page B unique content beta</p>",
            }
        }
    )
    result, _ = _crawl_with_mock(org_id, bot_id, "https://example.com/", handler=handler)

    assert result.pages_ingested == 3
    assert result.stopped_reason == "exhausted"
    assert len(result.documents) == 3
    by_uri = {d.source_uri: d for d in result.documents}
    assert by_uri["https://example.com/"].metadata_json == {
        "crawl_entry_url": "https://example.com/",
        "crawl_depth": 0,
    }
    assert by_uri["https://example.com/a"].metadata_json == {
        "crawl_entry_url": "https://example.com/",
        "crawl_depth": 1,
    }
    assert by_uri["https://example.com/b"].metadata_json == {
        "crawl_entry_url": "https://example.com/",
        "crawl_depth": 1,
    }
    for d in result.documents:
        assert d.source_type == "url"
        assert d.status == "ready"


# --- Same-registrable-domain filtering (security boundary) ---


def test_crawl_never_fetches_cross_registrable_domain_link() -> None:
    _, org_id, bot_id = _setup()
    handler = _site(
        {
            "example.com": {"/": '<p>Entry</p><a href="https://evil-external.com/x">ext</a>'},
            "evil-external.com": {"/x": "<p>should never be fetched</p>"},
        }
    )
    result, transport = _crawl_with_mock(org_id, bot_id, "https://example.com/", handler=handler)

    assert result.pages_ingested == 1
    hosts_fetched = {r.url.host for r in transport.requests}
    assert "evil-external.com" not in hosts_fetched


# --- Registrable-domain matching correctness (tldextract, not naive substring) ---


def test_crawl_follows_subdomains_of_entry_registrable_domain() -> None:
    _, org_id, bot_id = _setup()
    handler = _site(
        {
            "example.com": {"/": '<p>Entry</p><a href="https://www.example.com/w">w</a><a href="https://blog.example.com/b">b</a>'},
            "www.example.com": {"/w": "<p>www content</p>"},
            "blog.example.com": {"/b": "<p>blog content</p>"},
        }
    )
    result, transport = _crawl_with_mock(org_id, bot_id, "https://example.com/", handler=handler)

    hosts_fetched = {r.url.host for r in transport.requests if r.url.path != "/robots.txt"}
    assert hosts_fetched == {"example.com", "www.example.com", "blog.example.com"}
    assert result.pages_ingested == 3


def test_crawl_does_not_follow_different_public_suffix_domain() -> None:
    _, org_id, bot_id = _setup()
    handler = _site(
        {
            "example.com": {"/": '<p>Entry</p><a href="https://example.co.uk/x">uk</a>'},
            "example.co.uk": {"/x": "<p>different site entirely</p>"},
        }
    )
    result, transport = _crawl_with_mock(org_id, bot_id, "https://example.com/", handler=handler)

    hosts_fetched = {r.url.host for r in transport.requests}
    assert "example.co.uk" not in hosts_fetched
    assert result.pages_ingested == 1


def test_crawl_treats_distinct_github_io_sites_as_different_domains() -> None:
    _, org_id, bot_id = _setup()
    handler = _site(
        {
            "foo.github.io": {"/": '<p>Foo entry</p><a href="https://bar.github.io/">bar</a>'},
            "bar.github.io": {"/": "<p>should not be followed</p>"},
        }
    )
    result, transport = _crawl_with_mock(org_id, bot_id, "https://foo.github.io/", handler=handler)

    hosts_fetched = {r.url.host for r in transport.requests}
    assert "bar.github.io" not in hosts_fetched
    assert result.pages_ingested == 1


# --- Page-count cap ---


def test_crawl_page_limit_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_crawl_pages", 3)
    _, org_id, bot_id = _setup()
    pages = {"/": '<p>Entry</p><a href="/p1">1</a>'}
    for i in range(1, 10):
        pages[f"/p{i}"] = f'<p>Page {i} content</p><a href="/p{i + 1}">next</a>'
    handler = _site({"example.com": pages})

    result, _ = _crawl_with_mock(org_id, bot_id, "https://example.com/", handler=handler)

    assert result.stopped_reason == "page_limit"
    assert result.pages_fetched == 3
    assert result.pages_ingested == 3


# --- Depth cap ---


def test_crawl_depth_limit_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_crawl_depth", 2)
    monkeypatch.setattr(settings, "max_crawl_pages", 100)
    _, org_id, bot_id = _setup()
    # Linear chain: / (depth0) -> /p1 (depth1) -> /p2 (depth2) -> /p3 (depth3, beyond cap) -> /p4
    pages = {
        "/": '<p>Entry</p><a href="/p1">1</a>',
        "/p1": '<p>P1 unique</p><a href="/p2">2</a>',
        "/p2": '<p>P2 unique</p><a href="/p3">3</a>',
        "/p3": '<p>P3 unique -- beyond depth cap, never fetched</p><a href="/p4">4</a>',
    }
    handler = _site({"example.com": pages})

    result, transport = _crawl_with_mock(org_id, bot_id, "https://example.com/", handler=handler)

    assert result.stopped_reason == "depth_limit"
    fetched_paths = {r.url.path for r in transport.requests if r.url.path != "/robots.txt"}
    assert "/p3" not in fetched_paths
    assert result.pages_ingested == 3  # /, /p1, /p2 only


# --- Time-budget cap, with partial-results-persist proof ---


def test_crawl_time_budget_cap_persists_partial_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "crawl_time_budget_seconds", 0.05)
    monkeypatch.setattr(settings, "max_crawl_pages", 100)
    _, org_id, bot_id = _setup()
    pages = {"/": '<p>Entry unique alpha</p><a href="/p1">1</a>'}
    for i in range(1, 10):
        pages[f"/p{i}"] = f'<p>Slow page {i} unique</p><a href="/p{i + 1}">next</a>'
    handler = _site({"example.com": pages}, delay_seconds=0.08)

    result, _ = _crawl_with_mock(org_id, bot_id, "https://example.com/", handler=handler)

    assert result.stopped_reason == "time_budget"
    assert result.pages_ingested >= 1
    assert result.pages_ingested < 10  # budget genuinely cut it short

    doc_ids = [d.id for d in result.documents]
    stored_ids = asyncio.run(_document_ids_for_chatbot(bot_id))
    for doc_id in doc_ids:
        assert doc_id in stored_ids  # genuinely committed to the DB, not just in the response


# --- robots.txt caching (efficiency proof) ---


def test_crawl_fetches_robots_txt_exactly_once_per_host() -> None:
    _, org_id, bot_id = _setup()
    robots_calls: dict[str, int] = {}
    handler = _site(
        {
            "example.com": {
                "/": '<p>Entry</p><a href="/a">a</a><a href="/b">b</a>',
                "/a": "<p>content a unique</p>",
                "/b": "<p>content b unique</p>",
            }
        },
        robots_calls=robots_calls,
    )

    result, _ = _crawl_with_mock(org_id, bot_id, "https://example.com/", handler=handler)

    assert result.pages_ingested == 3
    assert robots_calls == {"example.com": 1}


# --- SSRF: every discovered link goes through the same validator ---


def test_crawl_rejects_discovered_link_pointing_at_unsafe_host() -> None:
    _, org_id, bot_id = _setup()
    handler = _site(
        {
            "example.com": {
                "/": '<p>Entry</p><a href="https://internal.example.com/admin">internal</a>',
            },
            "internal.example.com": {"/admin": "<p>should never be reached</p>"},
        }
    )
    # internal.example.com is same-registrable-domain as example.com (so it
    # survives domain filtering) but is configured to simulate resolving to
    # a private IP -- the SecureHTTPFetcher/URLValidator SSRF check must
    # still reject it, exactly as it would a direct single-URL ingest of
    # that same address.
    result, transport = _crawl_with_mock(
        org_id,
        bot_id,
        "https://example.com/",
        handler=handler,
        unsafe_hostnames=frozenset({"internal.example.com"}),
    )

    assert result.pages_ingested == 1
    assert result.pages_failed == 1
    hosts_fetched = {r.url.host for r in transport.requests}
    assert "internal.example.com" not in hosts_fetched


# --- Rate limiting ---


def test_crawl_rate_limited_after_5_per_hour() -> None:
    token, org_id, bot_id = _setup()
    headers = {"Authorization": f"Bearer {token}"}

    statuses = []
    for _ in range(6):
        r = client.post(
            f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/knowledge/documents/crawl",
            json={"url": "http://192.168.1.1/"},  # fails SSRF validation fast, deterministic, no real network
            headers=headers,
        )
        statuses.append(r.status_code)

    assert statuses[:5] == [422] * 5
    assert statuses[5] == 429


def test_single_url_ingestion_remains_unlimited() -> None:
    token, org_id, bot_id = _setup()
    headers = {"Authorization": f"Bearer {token}"}

    statuses = []
    for _ in range(6):
        r = client.post(
            f"/api/v1/organizations/{org_id}/chatbots/{bot_id}/knowledge/documents/url",
            json={"url": "http://192.168.1.1/"},
            headers=headers,
        )
        statuses.append(r.status_code)

    assert all(s == 422 for s in statuses)
    assert 429 not in statuses
