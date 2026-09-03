"""Platform-owner dashboard schemas — safe cross-organization DTOs.

The one deliberate cross-tenant read surface in this codebase (see
architecture.md §8a). Never serialize message/conversation content,
system_prompt, or credential material — aggregate/metadata signals
only, enumerated explicitly field by field, same discipline as the
public widget's response allowlist.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import ChatbotStatus, MembershipRole


class PlatformOrganizationSummary(BaseModel):
    id: int
    name: str
    slug: str
    created_at: datetime
    owner_email: str | None
    member_count: int
    chatbot_count: int
    last_activity_at: datetime | None
    disabled_at: datetime | None
    disabled_message: str | None


class PlatformOrganizationListResponse(BaseModel):
    items: list[PlatformOrganizationSummary]
    total: int
    limit: int
    offset: int


class PlatformMemberSummary(BaseModel):
    email: str
    role: MembershipRole
    joined_at: datetime


class PlatformChatbotSummary(BaseModel):
    name: str
    slug: str
    status: ChatbotStatus
    created_at: datetime


class PlatformOrganizationDetail(PlatformOrganizationSummary):
    members: list[PlatformMemberSummary]
    chatbots: list[PlatformChatbotSummary]
    message_count: int


class OrganizationDisableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str | None = None
