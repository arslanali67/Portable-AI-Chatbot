"""Link extraction for crawling — parses <a href> from already-fetched HTML.

No new fetch: reuses the HTML a page's ingestion already downloaded.
"""

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

_SKIP_SCHEMES = ("#", "mailto:", "tel:", "javascript:")


def extract_links(html: str, base_url: str) -> list[str]:
    """Absolute http(s) links found in html, resolved against base_url,
    fragment-stripped and deduped. Order preserved (first occurrence)."""
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    links: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith(_SKIP_SCHEMES):
            continue
        absolute = urljoin(base_url, href)
        if urlparse(absolute).scheme not in ("http", "https"):
            continue
        normalized = absolute.split("#", 1)[0]
        if normalized in seen:
            continue
        seen.add(normalized)
        links.append(normalized)
    return links
