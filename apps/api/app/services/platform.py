"""Platform-owner dashboard service — the one deliberate cross-tenant
read surface in this codebase (see architecture.md §8a).

Queries repositories directly for cross-org aggregates. Must never call
into any existing service method that assumes single-org scoping —
those services' trust boundary stays exactly as it is today.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Organization
from app.repositories.chatbot import ChatbotRepository
from app.repositories.conversation import ConversationRepository
from app.repositories.membership import MembershipRepository
from app.repositories.message import MessageRepository
from app.repositories.organization import OrganizationRepository
from app.schemas.platform import (
    PlatformChatbotSummary,
    PlatformMemberSummary,
    PlatformOrganizationDetail,
    PlatformOrganizationSummary,
)


class OrganizationNotFoundError(Exception):
    pass


class PlatformService:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.organizations = OrganizationRepository(db_session)
        self.memberships = MembershipRepository(db_session)
        self.chatbots = ChatbotRepository(db_session)
        self.conversations = ConversationRepository(db_session)
        self.messages = MessageRepository(db_session)

    async def _summaries_for(
        self, organizations: list[Organization]
    ) -> list[PlatformOrganizationSummary]:
        org_ids = [org.id for org in organizations]
        member_counts = await self.memberships.count_for_organizations(org_ids)
        owner_emails = await self.memberships.owner_emails_for_organizations(org_ids)
        chatbot_counts = await self.chatbots.count_for_organizations(org_ids)
        last_activity = await self.conversations.last_activity_for_organizations(org_ids)
        return [
            PlatformOrganizationSummary(
                id=org.id,
                name=org.name,
                slug=org.slug,
                created_at=org.created_at,
                owner_email=owner_emails.get(org.id),
                member_count=member_counts.get(org.id, 0),
                chatbot_count=chatbot_counts.get(org.id, 0),
                last_activity_at=last_activity.get(org.id),
                disabled_at=org.disabled_at,
                disabled_message=org.disabled_message,
            )
            for org in organizations
        ]

    async def list_organizations(
        self, *, limit: int, offset: int
    ) -> tuple[list[PlatformOrganizationSummary], int]:
        organizations, total = await self.organizations.list_all(limit=limit, offset=offset)
        return await self._summaries_for(organizations), total

    async def get_organization_detail(self, organization_id: int) -> PlatformOrganizationDetail:
        organization = await self.organizations.get(organization_id)
        if organization is None:
            raise OrganizationNotFoundError(organization_id)

        (summary,) = await self._summaries_for([organization])
        member_rows = await self.memberships.list_for_organization(organization_id)
        chatbots = await self.chatbots.list_for_organization(organization_id)
        message_count = await self.messages.count_for_organization(organization_id)

        return PlatformOrganizationDetail(
            **summary.model_dump(),
            members=[
                PlatformMemberSummary(email=email, role=membership.role, joined_at=membership.created_at)
                for membership, email, _full_name in member_rows
            ],
            chatbots=[
                PlatformChatbotSummary(
                    name=chatbot.name,
                    slug=chatbot.slug,
                    status=chatbot.status,
                    created_at=chatbot.created_at,
                )
                for chatbot in chatbots
            ],
            message_count=message_count,
        )

    async def disable_organization(
        self, organization_id: int, *, message: str | None
    ) -> PlatformOrganizationSummary:
        organization = await self.organizations.get(organization_id)
        if organization is None:
            raise OrganizationNotFoundError(organization_id)
        await self.organizations.disable(organization, message=message)
        await self.db.commit()
        await self.db.refresh(organization)
        (summary,) = await self._summaries_for([organization])
        return summary

    async def enable_organization(self, organization_id: int) -> PlatformOrganizationSummary:
        organization = await self.organizations.get(organization_id)
        if organization is None:
            raise OrganizationNotFoundError(organization_id)
        await self.organizations.enable(organization)
        await self.db.commit()
        await self.db.refresh(organization)
        (summary,) = await self._summaries_for([organization])
        return summary
