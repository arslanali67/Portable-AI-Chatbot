"""Chatbot service — business rules, lifecycle, tenant scoping."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.registry import model_registry, provider_registry
from app.models import Chatbot
from app.models.enums import ChatbotStatus
from app.repositories.chatbot import ChatbotRepository
from app.schemas.chatbot import ChatbotCreate, ChatbotUpdate
from app.services.ai_provider_override import AIProviderOverrideService


class ChatbotNotFoundError(Exception):
    pass


class DuplicateSlugError(Exception):
    pass


class InvalidStatusTransitionError(Exception):
    pass


class InvalidProviderModelError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


_ALLOWED_TRANSITIONS = {
    ChatbotStatus.DRAFT: {ChatbotStatus.ACTIVE, ChatbotStatus.ARCHIVED},
    ChatbotStatus.ACTIVE: {ChatbotStatus.ARCHIVED},
    ChatbotStatus.ARCHIVED: set(),
}


async def _validate_provider_model(
    db: AsyncSession, provider_id: str, model_id: str
) -> None:
    """Validate provider/model pair against the registries and platform-admin overrides.

    Chain: provider exists → provider enabled (registry) → provider not
    admin-disabled → model exists → model belongs to provider → model
    enabled (registry) → model not admin-disabled.
    """
    if not provider_registry.exists(provider_id):
        raise InvalidProviderModelError("unknown provider")
    provider = provider_registry.get(provider_id)
    if not provider.metadata.enabled:
        raise InvalidProviderModelError("provider is disabled")

    overrides = AIProviderOverrideService(db)
    if await overrides.is_provider_disabled(provider_id):
        raise InvalidProviderModelError("provider is disabled")

    model = model_registry.get(provider_id, model_id)
    if model is None:
        raise InvalidProviderModelError("unknown model for provider")
    if not model.enabled:
        raise InvalidProviderModelError("model is disabled")
    if await overrides.is_model_disabled(provider_id, model_id):
        raise InvalidProviderModelError("model is disabled")


class ChatbotService:
    def __init__(self, db_session: AsyncSession):
        self.chatbots = ChatbotRepository(db_session)

    async def create(self, organization_id: int, payload: ChatbotCreate) -> Chatbot:
        existing = await self.chatbots.get_by_slug_for_organization(
            organization_id, payload.slug
        )
        if existing is not None:
            raise DuplicateSlugError()

        await _validate_provider_model(
            self.chatbots.db, payload.provider_id, payload.model_id
        )

        chatbot = await self.chatbots.create(
            organization_id=organization_id,
            name=payload.name,
            slug=payload.slug,
            description=payload.description,
            system_prompt=payload.system_prompt,
            welcome_message=payload.welcome_message,
            language=payload.language,
            visibility=payload.visibility,
            provider_id=payload.provider_id,
            model_id=payload.model_id,
            rag_enabled=payload.rag_enabled,
            rag_top_k=payload.rag_top_k,
        )
        try:
            await self.chatbots.db.commit()
        except IntegrityError as exc:
            await self.chatbots.db.rollback()
            if "uq_chatbots_organization_slug" in str(exc.orig):
                raise DuplicateSlugError()
            raise
        await self.chatbots.db.refresh(chatbot)
        return chatbot

    async def get(self, organization_id: int, chatbot_id: int) -> Chatbot:
        chatbot = await self.chatbots.get_by_id_for_organization(organization_id, chatbot_id)
        if chatbot is None:
            raise ChatbotNotFoundError()
        return chatbot

    async def list(self, organization_id: int) -> list[Chatbot]:
        return await self.chatbots.list_for_organization(organization_id)

    async def update(
        self, organization_id: int, chatbot_id: int, payload: ChatbotUpdate
    ) -> Chatbot:
        chatbot = await self.get(organization_id, chatbot_id)
        if payload.slug is not None and payload.slug != chatbot.slug:
            existing = await self.chatbots.get_by_slug_for_organization(
                organization_id, payload.slug
            )
            if existing is not None:
                raise DuplicateSlugError()

        # If either side of the pair changes, re-validate the combined pair.
        if payload.provider_id is not None or payload.model_id is not None:
            await _validate_provider_model(
                self.chatbots.db,
                payload.provider_id or chatbot.provider_id,
                payload.model_id or chatbot.model_id,
            )

        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(chatbot, field, value)
        try:
            await self.chatbots.db.commit()
        except IntegrityError as exc:
            await self.chatbots.db.rollback()
            if "uq_chatbots_organization_slug" in str(exc.orig):
                raise DuplicateSlugError()
            raise
        await self.chatbots.db.refresh(chatbot)
        return chatbot

    async def _transition(
        self, organization_id: int, chatbot_id: int, target: ChatbotStatus
    ) -> Chatbot:
        chatbot = await self.get(organization_id, chatbot_id)
        if target not in _ALLOWED_TRANSITIONS.get(chatbot.status, set()):
            raise InvalidStatusTransitionError(
                f"cannot transition from {chatbot.status.value} to {target.value}"
            )
        chatbot.status = target
        await self.chatbots.db.commit()
        await self.chatbots.db.refresh(chatbot)
        return chatbot

    async def activate(self, organization_id: int, chatbot_id: int) -> Chatbot:
        return await self._transition(organization_id, chatbot_id, ChatbotStatus.ACTIVE)

    async def archive(self, organization_id: int, chatbot_id: int) -> Chatbot:
        return await self._transition(organization_id, chatbot_id, ChatbotStatus.ARCHIVED)

    async def delete(self, organization_id: int, chatbot_id: int) -> None:
        chatbot = await self.get(organization_id, chatbot_id)
        await self.chatbots.delete(chatbot)
        await self.chatbots.db.commit()
