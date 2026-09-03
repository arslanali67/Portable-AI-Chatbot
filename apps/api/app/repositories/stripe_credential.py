"""StripeCredential repository — the single-row (id=1) platform-wide
Stripe secret key. Mirrors AIProviderCredentialRepository's shape."""

from app.models.stripe_credential import StripeCredential
from sqlalchemy.ext.asyncio import AsyncSession

_SINGLETON_ID = 1


class StripeCredentialRepository:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def get(self) -> StripeCredential | None:
        return await self.db.get(StripeCredential, _SINGLETON_ID)

    async def upsert(self, encrypted_secret_key: bytes, updated_by: int) -> StripeCredential:
        credential = await self.get()
        if credential is None:
            credential = StripeCredential(id=_SINGLETON_ID)
            self.db.add(credential)
        credential.encrypted_secret_key = encrypted_secret_key
        credential.updated_by = updated_by
        return credential
