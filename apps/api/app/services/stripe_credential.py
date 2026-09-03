"""Platform-wide Stripe credential service — mirrors
AIProviderCredentialService's encrypt-on-write/decrypt-just-in-time
pattern, reusing the existing Fernet key (settings.ai_credential_encryption_key)
rather than introducing a second one. See architecture.md §8b."""

from cryptography.fernet import Fernet

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.stripe_credential import StripeCredential
from app.repositories.stripe_credential import StripeCredentialRepository
from app.repositories.user import UserRepository
from app.schemas.billing import StripeCredentialStatusResponse


def _mask(plaintext: str) -> str:
    return "•" * 8 + plaintext[-4:]


class StripeCredentialService:
    def __init__(self, db_session: AsyncSession) -> None:
        self.db = db_session
        self.credentials = StripeCredentialRepository(db_session)
        self._fernet = Fernet(settings.ai_credential_encryption_key.encode())

    async def get_status(self) -> StripeCredentialStatusResponse | None:
        credential = await self.credentials.get()
        if credential is None:
            return None
        return await self._to_status(credential)

    async def set_credential(
        self, secret_key: str, actor_user_id: int
    ) -> StripeCredentialStatusResponse:
        encrypted = self._fernet.encrypt(secret_key.encode())
        credential = await self.credentials.upsert(encrypted, actor_user_id)
        await self.db.commit()
        await self.db.refresh(credential)
        return await self._to_status(credential)

    async def resolve_decrypted(self) -> str | None:
        """Just-in-time decrypt for an actual Stripe API call. None means
        no platform Stripe key has been configured yet."""
        credential = await self.credentials.get()
        if credential is None:
            return None
        return self._fernet.decrypt(credential.encrypted_secret_key).decode()

    async def _to_status(self, credential: StripeCredential) -> StripeCredentialStatusResponse:
        plaintext = self._fernet.decrypt(credential.encrypted_secret_key).decode()
        updated_by_email = None
        if credential.updated_by is not None:
            user = await UserRepository(self.db).get(credential.updated_by)
            updated_by_email = user.email if user else None
        return StripeCredentialStatusResponse(
            masked_key=_mask(plaintext),
            updated_at=credential.updated_at,
            updated_by_email=updated_by_email,
        )
