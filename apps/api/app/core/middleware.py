"""HTTP middleware: request logging, body size limit, error handling.

- RequestLoggingMiddleware: records method, path, status, duration. Never
  logs bodies, headers, or tokens.
- BodySizeLimitMiddleware: rejects oversized JSON request bodies with 413.
- ErrorHandlingMiddleware: converts unhandled exceptions into safe JSON
  error responses — no stack traces, no internals.
"""

import logging
import time

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings

logger = logging.getLogger("portableai.http")

_HEALTH_PATHS = {"/api/v1/health", "/api/v1/ready", "/", "/openapi.json", "/docs"}


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_holder: dict[str, int] = {"status": 0}

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            method = scope.get("method", "")
            duration_ms = (time.perf_counter() - start) * 1000
            if path not in _HEALTH_PATHS:
                logger.info(
                    "%s %s %s %.1fms",
                    method,
                    path,
                    status_holder["status"],
                    duration_ms,
                )


class BodySizeLimitMiddleware:
    """Reject request bodies larger than `max_request_bytes` with 413."""

    def __init__(self, app: ASGIApp, max_bytes: int | None = None) -> None:
        self.app = app
        self.max_bytes = (
            max_bytes if max_bytes is not None else settings.max_request_bytes
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = None
        headers = scope.get("headers") or []
        for name, value in headers:
            if name == b"content-length":
                try:
                    content_length = int(value)
                except ValueError:
                    content_length = None
                break

        if content_length is not None and content_length > self.max_bytes:
            response = JSONResponse(
                {"detail": "Request body too large"},
                status_code=413,
            )
            await response(scope, receive, send)
            return

        original_receive = receive
        received = 0

        async def limited_receive() -> dict:
            nonlocal received
            message = await original_receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise BodyTooLargeError()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except BodyTooLargeError:
            response = JSONResponse(
                {"detail": "Request body too large"},
                status_code=413,
            )
            await response(scope, receive, send)


class BodyTooLargeError(Exception):
    pass


class ErrorHandlingMiddleware:
    """Convert unhandled exceptions into safe error responses.

    Logs the full exception server-side; the client only ever sees a generic
    message. `HTTPException`s are already handled by FastAPI upstream.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        except Exception as exc:  # noqa: BLE001 - last-resort safety net
            path = scope.get("path", "")
            logger.exception("Unhandled error on %s", path)
            response = JSONResponse(
                {"detail": "Internal server error"},
                status_code=500,
            )
            await response(scope, receive, send)