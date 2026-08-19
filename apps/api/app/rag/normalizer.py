"""Text normalization for knowledge ingestion."""

import re

_MULTI_WHITESPACE = re.compile(r"[ \t]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")


class EmptyTextError(Exception):
    pass


def normalize_text(text: str) -> str:
    """Normalize line endings, collapse repeated whitespace, preserve content."""
    if text is None or not text.strip():
        raise EmptyTextError("text must not be empty or whitespace")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _MULTI_NEWLINE.sub("\n\n", normalized)
    normalized = "\n".join(_MULTI_WHITESPACE.sub(" ", line) for line in normalized.split("\n"))
    return normalized.strip()
