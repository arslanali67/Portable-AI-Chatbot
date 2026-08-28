"""AI provider/model override service — platform-admin enable/disable,
layered on the code-owned registries (app/ai/registry.py).

Effective enablement is always `registry.enabled AND NOT overridden` —
this service can only narrow what the registry already allows, never
widen it. A provider/model with no override row behaves exactly as the
registry says (default: not disabled).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.ai_override import AIModelOverrideRepository, AIProviderOverrideRepository


class AIProviderOverrideService:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.providers = AIProviderOverrideRepository(db_session)
        self.models = AIModelOverrideRepository(db_session)

    async def is_provider_disabled(self, provider_id: str) -> bool:
        override = await self.providers.get(provider_id)
        return override is not None and override.disabled_at is not None

    async def is_model_disabled(self, provider_id: str, model_id: str) -> bool:
        override = await self.models.get(provider_id, model_id)
        return override is not None and override.disabled_at is not None

    async def disable_provider(self, provider_id: str, actor_user_id: int) -> None:
        await self.providers.disable(provider_id, actor_user_id)
        await self.db.commit()

    async def enable_provider(self, provider_id: str) -> None:
        await self.providers.enable(provider_id)
        await self.db.commit()

    async def disable_model(self, provider_id: str, model_id: str, actor_user_id: int) -> None:
        await self.models.disable(provider_id, model_id, actor_user_id)
        await self.db.commit()

    async def enable_model(self, provider_id: str, model_id: str) -> None:
        await self.models.enable(provider_id, model_id)
        await self.db.commit()
