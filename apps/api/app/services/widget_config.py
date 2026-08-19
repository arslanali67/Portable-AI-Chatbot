"""Widget config management — create/revoke per-chatbot public credentials."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WidgetConfig
from app.repositories.widget import WidgetConfigRepository, generate_public_key


class WidgetConfigNotFoundError(Exception):
    pass


class WidgetConfigService:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.configs = WidgetConfigRepository(db_session)

    async def create(self, chatbot_id: int, allowed_origins: list[str] | None = None) -> WidgetConfig:
        config = WidgetConfig(
            chatbot_id=chatbot_id,
            public_key=generate_public_key(),
            enabled=True,
            allowed_origins=allowed_origins or [],
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

    async def revoke(self, chatbot_id: int) -> None:
        from datetime import datetime, timezone

        config = await self.configs.get_by_public_key_session(chatbot_id)
        if config is None:
            raise WidgetConfigNotFoundError()
        config.revoked_at = datetime.now(timezone.utc)
        await self.db.commit()
