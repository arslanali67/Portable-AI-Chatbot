"""Widget repositories — public_key config + anonymous sessions."""

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import WidgetConfig, WidgetSession


def generate_public_key() -> str:
    return secrets.token_urlsafe(32)


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


class WidgetConfigRepository:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def get_by_public_key(self, public_key: str) -> WidgetConfig | None:
        result = await self.db.execute(
            select(WidgetConfig).where(WidgetConfig.public_key == public_key)
        )
        return result.scalar_one_or_none()

    async def get_by_public_key_session(self, chatbot_id: int) -> WidgetConfig | None:
        result = await self.db.execute(
            select(WidgetConfig)
            .where(WidgetConfig.chatbot_id == chatbot_id)
            .order_by(WidgetConfig.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


class WidgetSessionRepository:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def get_by_token(self, token: str) -> WidgetSession | None:
        result = await self.db.execute(
            select(WidgetSession).where(WidgetSession.session_token == token)
        )
        return result.scalar_one_or_none()

    async def create(self, chatbot_id: int) -> WidgetSession:
        session = WidgetSession(
            chatbot_id=chatbot_id,
            session_token=generate_session_token(),
            expires_at=datetime.now(timezone.utc)
            + timedelta(hours=settings.widget_session_ttl_hours),
        )
        self.db.add(session)
        return session
