"""Widget config admin schemas — create/update/read for the org-scoped
authenticated management surface. Distinct from app/schemas/public_widget.py,
which is the smaller, public-facing DTO returned to anonymous visitors.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import WidgetPosition

THEME_COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"


class WidgetConfigCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_origins: list[str] = Field(default_factory=list)
    theme_color: str | None = Field(default=None, pattern=THEME_COLOR_PATTERN)
    widget_position: WidgetPosition | None = None


class WidgetConfigUpdate(BaseModel):
    """Partial update. avatar_url is deliberately absent — it is server-set
    only, via the dedicated avatar-upload endpoint, never client-settable
    directly."""

    model_config = ConfigDict(extra="forbid")

    allowed_origins: list[str] | None = None
    theme_color: str | None = Field(default=None, pattern=THEME_COLOR_PATTERN)
    widget_position: WidgetPosition | None = None


class WidgetConfigAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_key: str
    enabled: bool
    revoked_at: datetime | None
    allowed_origins: list[str]
    theme_color: str | None
    widget_position: WidgetPosition | None
    avatar_url: str | None
