"""Secure HTTP fetcher — bounded redirects, size limit, SSRF-safe.

Every redirect re-validated through URLValidator. Response read is capped.
"""

import httpx

from app.core.config import settings
from app.rag.url_validator import URLValidator

ALLOWED_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}
ROBOTS_CONTENT_TYPES = {"text/plain", "text/html", "application/xhtml+xml"}


class FetchError(Exception):
    pass


class RedirectLimitError(FetchError):
    pass


class ResponseTooLargeError(FetchError):
    pass


class BadContentTypeError(FetchError):
    pass


class RobotsBlockedError(FetchError):
    pass


class SecureHTTPFetcher:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        validator: URLValidator | None = None,
    ) -> None:
        self._validator = validator or URLValidator()
        self._client = client or httpx.AsyncClient(timeout=settings.url_fetch_timeout)

    async def fetch_html(self, url: str, *, check_robots: bool = True) -> tuple[str, str]:
        """Returns (canonical_url, html_body)."""
        current = self._validator.validate(url)
        if check_robots and settings.url_respect_robots:
            await self._check_robots(current)
        url_after, body = await self._get_with_redirects(current.canonical)
        return url_after, body

    async def _check_robots(self, validated) -> None:
        origin = f"{validated.canonical.split('/', 3)[0]}//{validated.hostname}"
        robots_url = f"{origin}/robots.txt"
        try:
            status, body = await self._get_with_redirects_status(robots_url, allow_robots=True)
        except FetchError:
            raise RobotsBlockedError("robots.txt could not be checked safely")
        if status == 404:
            # No robots.txt — nothing disallowed.
            return
        path = validated.canonical.split("/", 3)[3] if "/" in validated.canonical else "/"
        if not path.startswith("/"):
            path = "/" + path
        if _robots_disallows(body, path):
            raise RobotsBlockedError("robots.txt disallows this URL")

    async def _get_with_redirects(self, url: str, *, allow_robots: bool = False) -> tuple[str, str]:
        current = url
        for _ in range(settings.url_max_redirects + 1):
            url_after, body, status, location, content_type = await self._get_once(current, allow_robots)
            if status in (301, 302, 303, 307, 308) and location:
                if _ >= settings.url_max_redirects:
                    raise RedirectLimitError("too many redirects")
                next_url = _resolve_redirect(current, location)
                validated = self._validator.validate(next_url)
                current = validated.canonical
                continue
            if status >= 400 and status < 500:
                raise FetchError("upstream client error")
            if status >= 500:
                raise FetchError("upstream server error")
            if not _content_type_allowed(content_type, allow_robots=allow_robots):
                raise BadContentTypeError("unsupported content type")
            return current, body
        raise RedirectLimitError("too many redirects")

    async def _get_with_redirects_status(
        self, url: str, *, allow_robots: bool = False
    ) -> tuple[int, str]:
        """Like _get_with_redirects but returns (status, body); 404 is allowed
        through so robots handling can distinguish 'no robots.txt'."""
        current = url
        for _ in range(settings.url_max_redirects + 1):
            url_after, body, status, location, content_type = await self._get_once(current, allow_robots)
            if status in (301, 302, 303, 307, 308) and location:
                if _ >= settings.url_max_redirects:
                    raise RedirectLimitError("too many redirects")
                next_url = _resolve_redirect(current, location)
                validated = self._validator.validate(next_url)
                current = validated.canonical
                continue
            if status == 404:
                return status, body
            if status >= 400 and status < 500:
                raise FetchError("upstream client error")
            if status >= 500:
                raise FetchError("upstream server error")
            if not _content_type_allowed(content_type, allow_robots=allow_robots):
                raise BadContentTypeError("unsupported content type")
            return status, body
        raise RedirectLimitError("too many redirects")

    async def _get_once(
        self, url: str, allow_robots: bool = False
    ) -> tuple[str, str, int, str | None, str | None]:
        headers = {"User-Agent": settings.url_user_agent}
        try:
            async with self._client.stream("GET", url, headers=headers) as response:
                content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                is_redirect = response.status_code in (301, 302, 303, 307, 308)
                if (
                    response.status_code < 400
                    and not is_redirect
                    and not _content_type_allowed(content_type, allow_robots=allow_robots)
                ):
                    raise BadContentTypeError("unsupported content type")
                body = b""
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > settings.url_max_response_bytes:
                        raise ResponseTooLargeError("response too large")
                return (
                    str(response.url),
                    body.decode("utf-8", errors="replace"),
                    response.status_code,
                    response.headers.get("location"),
                    content_type,
                )
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
            raise FetchError("fetch failed") from exc


def _content_type_allowed(content_type: str | None, *, allow_robots: bool = False) -> bool:
    allowed = ROBOTS_CONTENT_TYPES if allow_robots else ALLOWED_CONTENT_TYPES
    return content_type in allowed


def _resolve_redirect(base: str, location: str) -> str:
    from urllib.parse import urljoin

    return urljoin(base, location)


def _robots_disallows(body: str, path: str) -> bool:
    """Minimal robots.txt parser: honor first matching User-agent group.

    Simplistic but deterministic; not a full RFC 9309 implementation.
    """
    path = path or "/"
    for agent, rules in _parse_robots(body):
        if agent == "*":
            for rule in rules:
                if path.startswith(rule):
                    return True
            return False
    return False


def _parse_robots(body: str):
    """Yield (user_agent, disallow_paths) groups."""
    groups = []
    current_agent = None
    current_rules = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if current_agent is not None:
                groups.append((current_agent, current_rules))
            current_agent = value
            current_rules = []
        elif key == "disallow" and current_agent is not None:
            if value:
                current_rules.append(value)
    if current_agent is not None:
        groups.append((current_agent, current_rules))
    return groups
