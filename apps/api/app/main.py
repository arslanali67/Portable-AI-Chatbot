from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.middleware import (
    BodySizeLimitMiddleware,
    ErrorHandlingMiddleware,
    RequestLoggingMiddleware,
)
from app.services.widget_avatar import safe_avatar_path

setup_logging()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# Starlette applies middleware in reverse order of addition: the LAST added is
# the OUTERMOST. Error handling must be outermost, then logging, then body
# limit, then CORS/trusted hosts.
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
if settings.trusted_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(ErrorHandlingMiddleware)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/widget.js", include_in_schema=False)
def widget_js() -> FileResponse:
    return FileResponse(_widget_script_path(), media_type="application/javascript")


@app.get("/widget-avatars/{filename}", include_in_schema=False)
def widget_avatar(filename: str) -> FileResponse:
    path = safe_avatar_path(filename)
    if path is None or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return FileResponse(path)


def _widget_script_path() -> Path:
    """Resolve packages/widget/widget.js for the dev repo and the API image.

    Dev layout: apps/api/app/main.py -> parents[2] is the repo root.
    Container layout: /app/app/main.py -> parents[0] is /app, where the image
    bundles packages/widget/widget.js (see apps/api/Dockerfile).
    """
    here = Path(__file__).resolve().parent
    for depth in (0, 2):
        try:
            base = here.parents[depth]
        except IndexError:
            continue
        candidate = base / "packages" / "widget" / "widget.js"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("packages/widget/widget.js not found")


@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    return {"name": settings.app_name, "version": settings.app_version, "status": "running"}