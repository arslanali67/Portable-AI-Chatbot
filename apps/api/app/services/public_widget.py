"""Public widget service — session/config/chat orchestration.

Thin public boundary over existing runtime. Server derives org/chatbot from
public_key/session; client never supplies them.
"""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Chatbot, User, WidgetConfig, WidgetSession
from app.models.enums import ChatbotStatus, ChatbotVisibility
from app.repositories.chatbot import ChatbotRepository
from app.repositories.conversation import ConversationRepository
from app.repositories.message import MessageRepository
from app.repositories.organization import OrganizationRepository
from app.repositories.user import UserRepository
from app.repositories.widget import WidgetConfigRepository, WidgetSessionRepository
from app.schemas.chat_runtime import ChatRequest

_DISABLED_FALLBACK_MESSAGE = "This assistant is currently unavailable."


class WidgetError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class OriginDeniedError(WidgetError):
    pass


class PublicChatbotUnavailableError(WidgetError):
    pass


class InvalidSessionError(WidgetError):
    pass


class OrganizationDisabledError(WidgetError):
    pass


class PublicWidgetService:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.configs = WidgetConfigRepository(db_session)
        self.sessions = WidgetSessionRepository(db_session)
        self.chatbots = ChatbotRepository(db_session)
        self.users = UserRepository(db_session)
        self.conversations = ConversationRepository(db_session)
        self.messages = MessageRepository(db_session)
        self.organizations = OrganizationRepository(db_session)

    async def _check_organization_enabled(self, organization_id: int) -> None:
        """Never let a disabled organization's widget proceed to session
        creation or chat/stream — shows the platform admin's configured
        message, or a generic fallback if none was set."""
        organization = await self.organizations.get(organization_id)
        if organization is not None and organization.disabled_at is not None:
            raise OrganizationDisabledError(
                403, organization.disabled_message or _DISABLED_FALLBACK_MESSAGE
            )

    async def _resolve_by_public_key(self, public_key: str) -> tuple[WidgetConfig, Chatbot]:
        config = await self.configs.get_by_public_key(public_key)
        if config is None or config.revoked_at is not None or not config.enabled:
            raise PublicChatbotUnavailableError(404, "Chatbot not found")

        chatbot = await self.chatbots.get_public(config.chatbot_id)
        if chatbot is None or chatbot.status != ChatbotStatus.ACTIVE or chatbot.visibility != ChatbotVisibility.PUBLIC:
            raise PublicChatbotUnavailableError(404, "Chatbot not found")

        await self._check_organization_enabled(chatbot.organization_id)
        return config, chatbot

    async def get_public_config(self, public_key: str) -> tuple[WidgetConfig, Chatbot]:
        """Theme/language-only lookup for the eager launcher-theming fetch.
        No session created, no DB write — a pure read, unlike create_session."""
        return await self._resolve_by_public_key(public_key)

    async def create_session(self, public_key: str, origin: str | None) -> tuple[WidgetSession, WidgetConfig, Chatbot]:
        config, chatbot = await self._resolve_by_public_key(public_key)
        self._check_origin(config, origin)

        session = await self.sessions.create(config.chatbot_id)
        await self.db.commit()
        await self.db.refresh(session)
        return session, config, chatbot

    async def resolve_session(self, session_token: str, origin: str | None) -> tuple[WidgetSession, WidgetConfig, Chatbot]:
        session = await self.sessions.get_by_token(session_token)
        if session is None or session.expires_at <= datetime.now(timezone.utc):
            raise InvalidSessionError(403, "Invalid or expired session")

        config = await self.configs.get_by_public_key_session(session.chatbot_id)
        if config is None or config.revoked_at is not None or not config.enabled:
            raise PublicChatbotUnavailableError(404, "Chatbot not found")

        chatbot = await self.chatbots.get_public(session.chatbot_id)
        if chatbot is None or chatbot.status != ChatbotStatus.ACTIVE or chatbot.visibility != ChatbotVisibility.PUBLIC:
            raise PublicChatbotUnavailableError(404, "Chatbot not found")

        await self._check_organization_enabled(chatbot.organization_id)
        self._check_origin(config, origin)
        session.last_seen_at = datetime.now(timezone.utc)
        await self.db.commit()
        return session, config, chatbot

    async def get_or_create_placeholder_user(self, organization_id: int) -> User:
        email = f"widget-{organization_id}@portableai.local"
        user = await self.users.get_by_email(email)
        if user is None:
            user = await self.users.create(
                email=email,
                password_hash="!",
                full_name=settings.widget_placeholder_user_name,
            )
            user.is_active = False
            await self.db.commit()
            await self.db.refresh(user)
        return user

    async def ensure_conversation(
        self, organization_id: int, chatbot_id: int, user: User
    ) -> object:
        conversation = await self.conversations.create(
            organization_id=organization_id,
            chatbot_id=chatbot_id,
            user_id=user.id,
            title="Widget conversation",
        )
        await self.db.commit()
        await self.db.refresh(conversation)
        return conversation

    @staticmethod
    def _check_origin(config: WidgetConfig, origin: str | None) -> None:
        allowed = config.allowed_origins or []
        if not allowed:
            return  # no origin restrictions configured
        if not origin:
            raise OriginDeniedError(403, "Origin required")
        if origin not in allowed and "*" not in allowed:
            raise OriginDeniedError(403, "Origin not allowed")
