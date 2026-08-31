"""Chatbot repository — tenant-scoped data access.

Authenticated flows must use the organization-scoped lookups
(`get_by_id_for_organization`, `list_for_organization`,
`get_by_slug_for_organization`) — there is no unsafe global lookup for
authenticated callers.

`get_public` is the single unscoped-by-organization read. It exists only for
the public widget boundary: the `chatbot_id` is always derived server-side from
a `public_key` / `session_token` lookup (`WidgetConfig`/`WidgetSession` rows),
never from client input, and the caller immediately re-verifies status and
visibility before any data is exposed. It is therefore safe by construction and
must not be used by authenticated organization flows.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chatbot


class ChatbotRepository:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def get_public(self, chatbot_id: int) -> Chatbot | None:
        """Unscoped-by-organization lookup for the public widget boundary only.

        Safe because callers pass a server-derived chatbot_id (from a widget
        public_key/session) and re-check status/visibility before exposing any
        data. See module docstring.
        """
        return await self.db.get(Chatbot, chatbot_id)

    async def create(
        self,
        *,
        organization_id: int,
        name: str,
        slug: str,
        description: str,
        system_prompt: str,
        welcome_message: str,
        language: str,
        visibility,
        provider_id: str,
        model_id: str,
        rag_enabled: bool = True,
        rag_top_k: int | None = None,
    ) -> Chatbot:
        chatbot = Chatbot(
            organization_id=organization_id,
            name=name,
            slug=slug,
            description=description,
            system_prompt=system_prompt,
            welcome_message=welcome_message,
            language=language,
            visibility=visibility,
            provider_id=provider_id,
            model_id=model_id,
            rag_enabled=rag_enabled,
            rag_top_k=rag_top_k,
        )
        self.db.add(chatbot)
        return chatbot

    async def get_by_id_for_organization(
        self, organization_id: int, chatbot_id: int
    ) -> Chatbot | None:
        result = await self.db.execute(
            select(Chatbot).where(
                Chatbot.id == chatbot_id, Chatbot.organization_id == organization_id
            )
        )
        return result.scalar_one_or_none()

    async def list_for_organization(self, organization_id: int) -> list[Chatbot]:
        result = await self.db.execute(
            select(Chatbot)
            .where(Chatbot.organization_id == organization_id)
            .order_by(Chatbot.id)
        )
        return list(result.scalars().all())

    async def get_by_slug_for_organization(
        self, organization_id: int, slug: str
    ) -> Chatbot | None:
        result = await self.db.execute(
            select(Chatbot).where(
                Chatbot.organization_id == organization_id, Chatbot.slug == slug
            )
        )
        return result.scalar_one_or_none()

    async def delete(self, chatbot: Chatbot) -> None:
        await self.db.delete(chatbot)
