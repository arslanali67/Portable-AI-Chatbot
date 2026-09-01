"""BYOK AI provider credential repository — tenant-scoped data access."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_provider_credential import AIProviderCredential


class AIProviderCredentialRepository:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def get(
        self, organization_id: int, provider_id: str
    ) -> AIProviderCredential | None:
        result = await self.db.execute(
            select(AIProviderCredential).where(
                AIProviderCredential.organization_id == organization_id,
                AIProviderCredential.provider_id == provider_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_organization(self, organization_id: int) -> list[AIProviderCredential]:
        result = await self.db.execute(
            select(AIProviderCredential)
            .where(AIProviderCredential.organization_id == organization_id)
            .order_by(AIProviderCredential.provider_id)
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        organization_id: int,
        provider_id: str,
        encrypted_key: bytes,
        updated_by: int,
    ) -> AIProviderCredential:
        credential = await self.get(organization_id, provider_id)
        if credential is None:
            credential = AIProviderCredential(
                organization_id=organization_id, provider_id=provider_id
            )
            self.db.add(credential)
        credential.encrypted_key = encrypted_key
        credential.updated_by = updated_by
        return credential

    async def delete(self, credential: AIProviderCredential) -> None:
        await self.db.delete(credential)
