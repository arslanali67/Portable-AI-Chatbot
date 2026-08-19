"""URL validation — SSRF protection.

Parse, normalize, validate scheme/host/port/credentials, resolve hostname,
check every resolved IP against unsafe ranges. Not claimed as perfect SSRF
defense (DNS rebinding window exists).
"""

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443}


class InvalidURLError(Exception):
    pass


class UnsafeURLError(Exception):
    pass


@dataclass(frozen=True)
class ValidatedURL:
    canonical: str
    hostname: str
    port: int


def _is_unsafe_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )


class URLValidator:
    def validate(self, url: str) -> ValidatedURL:
        parsed = urlparse(url)
        if parsed.scheme not in ALLOWED_SCHEMES:
            raise InvalidURLError("scheme not allowed")
        if not parsed.hostname:
            raise InvalidURLError("missing hostname")
        if parsed.username or parsed.password:
            raise UnsafeURLError("credentials in URL are not allowed")

        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in ALLOWED_PORTS:
            raise UnsafeURLError("port not allowed")

        hostname = parsed.hostname.lower()

        # Literal IP fast-path (also covers localhost/private literals).
        try:
            ip = ipaddress.ip_address(hostname)
            if _is_unsafe_ip(str(ip)):
                raise UnsafeURLError("unsafe IP address")
            return ValidatedURL(canonical=self._canonicalize(parsed, hostname, port), hostname=hostname, port=port)
        except ValueError:
            pass

        if hostname in ("localhost",):
            raise UnsafeURLError("unsafe hostname")

        # Resolve hostname and check every resolved IP.
        try:
            infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise InvalidURLError("hostname could not be resolved") from exc
        if not infos:
            raise InvalidURLError("hostname could not be resolved")

        for info in infos:
            ip_str = info[4][0]
            if _is_unsafe_ip(ip_str):
                raise UnsafeURLError("hostname resolves to an unsafe IP")

        return ValidatedURL(canonical=self._canonicalize(parsed, hostname, port), hostname=hostname, port=port)

    @staticmethod
    def _canonicalize(parsed, hostname: str, port: int) -> str:
        import posixpath

        scheme = parsed.scheme.lower()
        default_port = 443 if scheme == "https" else 80
        netloc = hostname if port == default_port else f"{hostname}:{port}"
        path = parsed.path or "/"
        normalized_path = posixpath.normpath(path)
        if not normalized_path.startswith("/"):
            normalized_path = "/" + normalized_path
        return urlunparse((scheme, netloc, normalized_path, "", parsed.query, ""))
