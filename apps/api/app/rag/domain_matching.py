"""Registrable-domain comparison for crawl link filtering.

Public-suffix-list aware (via tldextract) so subdomains of the same site
match (www.example.com / blog.example.com -> example.com) but distinct
sites under a shared public suffix don't (example.com != example.co.uk;
foo.github.io != bar.github.io). include_psl_private_domains=True is
required for the github.io case: it's PSL-listed under "PRIVATE", not
"ICANN", so without this flag tldextract treats "io" as the suffix and
both hosts collapse to the same "github.io" registrable domain.

suffix_list_urls=() disables live HTTP fetches of the public suffix list
at runtime, using the snapshot bundled with the package instead — no
network dependency, consistent with this codebase's offline-safe tests.
"""

import tldextract

_extract = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)


def registrable_domain(hostname: str) -> str:
    return _extract(hostname).top_domain_under_public_suffix


def same_registrable_domain(hostname_a: str, hostname_b: str) -> bool:
    a = registrable_domain(hostname_a)
    b = registrable_domain(hostname_b)
    return bool(a) and a == b
