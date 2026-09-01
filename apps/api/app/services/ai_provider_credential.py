"""BYOK AI provider credential service.

Encrypts on write, decrypts only just-in-time when actually needed
(save-time validation, status masking, or a real chat request) — plaintext
is never held longer than the single call that needs it, never logged.
"""

from cryptography.fernet import Fernet

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.contracts import AIMessage, AIMessageRole, AIRequest
from app.ai.exceptions import AIError
from app.ai.model_registry import ModelRegistry
from app.ai.provider_registry import ProviderRegistry
from app.core.config import settings
from app.models.ai_provider_credential import AIProviderCredential
from app.repositories.ai_provider_credential import AIProviderCredentialRepository
from app.repositories.user import UserRepository
from app.schemas.ai_provider_credential import CredentialStatusResponse


class UnknownProviderError(Exception):
    pass


class InvalidCredentialError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class CredentialNotFoundError(Exception):
    pass


def _mask(plaintext: str) -> str:
    return "•" * 8 + plaintext[-4:]


class AIProviderCredentialService:
    def __init__(
        self,
        db_session: AsyncSession,
        providers: ProviderRegistry,
        models: ModelRegistry,
    ) -> None:
        self.db = db_session
        self.credentials = AIProviderCredentialRepository(db_session)
        self.providers = providers
        self.models = models
        self._fernet = Fernet(settings.ai_credential_encryption_key.encode())

    async def list_status(self, organization_id: int) -> list[CredentialStatusResponse]:
        rows = await self.credentials.list_for_organization(organization_id)
        return [await self._to_status(row) for row in rows]

    async def set_credential(
        self, organization_id: int, provider_id: str, api_key: str, actor_user_id: int
    ) -> CredentialStatusResponse:
        if not self.providers.exists(provider_id):
            raise UnknownProviderError(provider_id)
        await self._validate(provider_id, api_key)
        encrypted = self._fernet.encrypt(api_key.encode())
        credential = await self.credentials.upsert(
            organization_id, provider_id, encrypted, actor_user_id
        )
        await self.db.commit()
        await self.db.refresh(credential)
        return await self._to_status(credential)

    async def remove_credential(self, organization_id: int, provider_id: str) -> None:
        credential = await self.credentials.get(organization_id, provider_id)
        if credential is None:
            raise CredentialNotFoundError(provider_id)
        await self.credentials.delete(credential)
        await self.db.commit()

    async def resolve_decrypted(self, organization_id: int, provider_id: str) -> str | None:
        """Just-in-time decrypt for an actual chat request. Returns None when
        no BYOK credential is set — caller falls back to the platform key."""
        credential = await self.credentials.get(organization_id, provider_id)
        if credential is None:
            return None
        return self._fernet.decrypt(credential.encrypted_key).decode()

    async def _validate(self, provider_id: str, api_key: str) -> None:
        provider = self.providers.get(provider_id)
        models = self.models.list(provider_id)
        model_id = models[0].model_id if models else provider_id
        request = AIRequest(
            provider_id=provider_id,
            model_id=model_id,
            messages=[AIMessage(role=AIMessageRole.USER, content="ping")],
            max_tokens=1,
        )
        try:
            await provider.generate(request, credential_override=api_key)
        except AIError as exc:
            raise InvalidCredentialError(str(exc)) from exc

    async def _to_status(self, credential: AIProviderCredential) -> CredentialStatusResponse:
        plaintext = self._fernet.decrypt(credential.encrypted_key).decode()
        updated_by_email = None
        if credential.updated_by is not None:
            user = await UserRepository(self.db).get(credential.updated_by)
            updated_by_email = user.email if user else None
        return CredentialStatusResponse(
            provider_id=credential.provider_id,
            masked_key=_mask(plaintext),
            updated_at=credential.updated_at,
            updated_by_email=updated_by_email,
        )
