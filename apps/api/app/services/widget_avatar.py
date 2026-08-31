"""Widget avatar upload — local-disk storage for chatbot widget branding.

Filenames are always server-generated (UUID4 hex + a validated extension
derived from the file's own magic bytes); a client-supplied filename or
Content-Type is never trusted and never used to construct a filesystem path.
"""

import re
import uuid
from pathlib import Path

from app.core.config import settings

# Server-generated filenames only match this shape — anything else (including
# any path-traversal attempt) is rejected before touching the filesystem.
FILENAME_PATTERN = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp)$")

AVATAR_URL_PREFIX = "/widget-avatars/"


class InvalidImageError(Exception):
    pass


class ImageTooLargeError(Exception):
    pass


def sniff_image_extension(content: bytes) -> str | None:
    """Identify PNG/JPEG/WebP by magic bytes. Returns None for anything else,
    regardless of what extension or Content-Type the client claimed."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(content) >= 12 and content[0:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    return None


def upload_dir() -> Path:
    path = Path(settings.widget_avatar_upload_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_avatar_path(filename: str) -> Path | None:
    """Resolve a served filename to a path inside the upload dir, or None if
    the filename doesn't match the server-generated shape (rejects any
    traversal attempt without ever building a path from client input)."""
    if not FILENAME_PATTERN.match(filename):
        return None
    base = upload_dir().resolve()
    candidate = (base / filename).resolve()
    if candidate.parent != base:
        return None
    return candidate


def save_avatar(content: bytes) -> str:
    """Validate + save; returns the served root-relative URL path."""
    if len(content) > settings.widget_avatar_max_bytes:
        raise ImageTooLargeError()
    extension = sniff_image_extension(content)
    if extension is None:
        raise InvalidImageError()
    filename = f"{uuid.uuid4().hex}.{extension}"
    (upload_dir() / filename).write_bytes(content)
    return AVATAR_URL_PREFIX + filename


def delete_avatar(avatar_url: str | None) -> None:
    """Best-effort delete of a previously-stored avatar. Silently ignores a
    missing/foreign/malformed value — replacing an avatar must never fail the
    request because the old file was already gone."""
    if not avatar_url or not avatar_url.startswith(AVATAR_URL_PREFIX):
        return
    filename = avatar_url[len(AVATAR_URL_PREFIX):]
    path = safe_avatar_path(filename)
    if path is not None and path.is_file():
        path.unlink()
