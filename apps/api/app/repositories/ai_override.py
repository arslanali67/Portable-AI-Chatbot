"""AI provider/model override repositories — thin platform-admin toggles
layered on top of the code-owned registries (app/ai/registry.py)."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_model_override import AIModelOverride
from app.models.ai_provider_override import AIProviderOverride


class AIProviderOverrideRepository:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def get(self, provider_id: str) -> AIProviderOverride | None:
        result = await self.db.execute(
            select(AIProviderOverride).where(AIProviderOverride.provider_id == provider_id)
        )
        return result.scalar_one_or_none()

    async def disable(self, provider_id: str, actor_user_id: int) -> AIProviderOverride:
        override = await self.get(provider_id)
        if override is None:
            override = AIProviderOverride(provider_id=provider_id)
            self.db.add(override)
        override.disabled_at = datetime.now(timezone.utc)
        override.disabled_by = actor_user_id
        return override

    async def enable(self, provider_id: str) -> None:
        override = await self.get(provider_id)
        if override is not None:
            override.disabled_at = None
            override.disabled_by = None


class AIModelOverrideRepository:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def get(self, provider_id: str, model_id: str) -> AIModelOverride | None:
        result = await self.db.execute(
            select(AIModelOverride).where(
                AIModelOverride.provider_id == provider_id,
                AIModelOverride.model_id == model_id,
            )
        )
        return result.scalar_one_or_none()

    async def disable(
        self, provider_id: str, model_id: str, actor_user_id: int
    ) -> AIModelOverride:
        override = await self.get(provider_id, model_id)
        if override is None:
            override = AIModelOverride(provider_id=provider_id, model_id=model_id)
            self.db.add(override)
        override.disabled_at = datetime.now(timezone.utc)
        override.disabled_by = actor_user_id
        return override

    async def enable(self, provider_id: str, model_id: str) -> None:
        override = await self.get(provider_id, model_id)
        if override is not None:
            override.disabled_at = None
            override.disabled_by = None
