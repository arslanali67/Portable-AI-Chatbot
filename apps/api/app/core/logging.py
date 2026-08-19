"""Structured application logging.

Redaction helpers ensure secrets never reach logs. A request-logging
middleware records method/path/status/duration without bodies or headers.
"""

import logging
import sys
from typing import Any

from app.core.config import settings

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "token",
    "jwt",
    "password",
    "password_hash",
    "secret",
    "authorization",
    "x-api-key",
    "cookie",
}


def redact_dict(value: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive keys within a plain dict, recursively."""
    out: dict[str, Any] = {}
    for k, v in value.items():
        if str(k).lower() in _SENSITIVE_KEYS:
            out[k] = "***"
        elif isinstance(v, dict):
            out[k] = redact_dict(v)
        else:
            out[k] = v
    return out


def setup_logging() -> None:
    """Configure root logging for the application."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger with app defaults applied."""
    return logging.getLogger(name)