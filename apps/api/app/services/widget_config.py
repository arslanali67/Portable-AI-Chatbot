"""Widget config management — create/read/update/revoke per-chatbot public
credentials, plus avatar upload (local-disk storage, replace-not-accumulate).
"""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WidgetConfig
from app.models.enums import WidgetPosition
from app.repositories.widget import WidgetConfigRepository, generate_public_key
from app.services.widget_avatar import (
    ImageTooLargeError,
    InvalidImageError,
    delete_avatar,
    save_avatar,
)

__all__ = [
    "WidgetConfigNotFoundError",
    "WidgetConfigService",
    "ImageTooLargeError",
    "InvalidImageError",
]


class WidgetConfigNotFoundError(Exception):
    pass


class WidgetConfigService:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.configs = WidgetConfigRepository(db_session)

    async def create(
        self,
        chatbot_id: int,
        allowed_origins: list[str] | None = None,
        theme_color: str | None = None,
        widget_position: WidgetPosition | None = None,
    ) -> WidgetConfig:
        config = WidgetConfig(
            chatbot_id=chatbot_id,
            public_key=generate_public_key(),
            enabled=True,
            allowed_origins=allowed_origins or [],
            theme_color=theme_color,
            widget_position=widget_position,
        )
        self.db.add(config)
        await self.db.commit()
        await self.db.refresh(config)
        return config

    async def get(self, chatbot_id: int) -> WidgetConfig:
        config = await self.configs.get_by_public_key_session(chatbot_id)
        if config is None:
            raise WidgetConfigNotFoundError()
        return config

    async def update(self, chatbot_id: int, changes: dict) -> WidgetConfig:
        config = await self.get(chatbot_id)
        for field, value in changes.items():
            setattr(config, field, value)
        await self.db.commit()
        await self.db.refresh(config)
        return config

    async def set_avatar(self, chatbot_id: int, content: bytes) -> WidgetConfig:
        """Validate + store a new avatar, replacing (not accumulating) any
        previous file. Raises ImageTooLargeError/InvalidImageError from
        app.services.widget_avatar on invalid input."""
        config = await self.get(chatbot_id)
        new_url = save_avatar(content)
        old_url = config.avatar_url
        config.avatar_url = new_url
        await self.db.commit()
        await self.db.refresh(config)
        delete_avatar(old_url)
        return config

    async def revoke(self, chatbot_id: int) -> None:
        config = await self.configs.get_by_public_key_session(chatbot_id)
        if config is None:
            raise WidgetConfigNotFoundError()
        config.revoked_at = datetime.now(timezone.utc)
        await self.db.commit()
