"""AI management service — read-only discovery over the registries, plus
platform-admin enable/disable mutation via AIProviderOverrideService.

Router stays thin; all registry access and validation lives here.
"""

from app.ai.metadata import ModelMetadata, ProviderMetadata
from app.ai.model_registry import ModelRegistry
from app.ai.provider_registry import ProviderRegistry
from app.schemas.ai_management import ModelResponse, ProviderResponse
from app.services.ai_provider_override import AIProviderOverrideService


class ProviderNotFoundError(Exception):
    pass


class ModelNotFoundError(Exception):
    pass


class AIManagementService:
    def __init__(
        self,
        providers: ProviderRegistry,
        models: ModelRegistry,
        overrides: AIProviderOverrideService,
    ) -> None:
        self.providers = providers
        self.models = models
        self.overrides = overrides

    async def list_providers(self) -> list[ProviderResponse]:
        return [await self._provider_dto(p.metadata) for p in self.providers.list()]

    async def get_provider(self, provider_id: str) -> ProviderResponse:
        if not self.providers.exists(provider_id):
            raise ProviderNotFoundError()
        return await self._provider_dto(self.providers.get(provider_id).metadata)

    async def list_models(self, provider_id: str) -> list[ModelResponse]:
        if not self.providers.exists(provider_id):
            raise ProviderNotFoundError()
        return [await self._model_dto(m) for m in self.models.list(provider_id)]

    async def get_model(self, provider_id: str, model_id: str) -> ModelResponse:
        if not self.providers.exists(provider_id):
            raise ProviderNotFoundError()
        model = self.models.get(provider_id, model_id)
        if model is None:
            raise ModelNotFoundError()
        return await self._model_dto(model)

    async def set_provider_disabled(
        self, provider_id: str, disabled: bool, actor_user_id: int
    ) -> ProviderResponse:
        if not self.providers.exists(provider_id):
            raise ProviderNotFoundError()
        if disabled:
            await self.overrides.disable_provider(provider_id, actor_user_id)
        else:
            await self.overrides.enable_provider(provider_id)
        return await self.get_provider(provider_id)

    async def set_model_disabled(
        self, provider_id: str, model_id: str, disabled: bool, actor_user_id: int
    ) -> ModelResponse:
        if not self.providers.exists(provider_id):
            raise ProviderNotFoundError()
        if self.models.get(provider_id, model_id) is None:
            raise ModelNotFoundError()
        if disabled:
            await self.overrides.disable_model(provider_id, model_id, actor_user_id)
        else:
            await self.overrides.enable_model(provider_id, model_id)
        return await self.get_model(provider_id, model_id)

    async def _provider_dto(self, metadata: ProviderMetadata) -> ProviderResponse:
        overridden = await self.overrides.is_provider_disabled(metadata.provider_id)
        return ProviderResponse(
            provider_id=metadata.provider_id,
            display_name=metadata.display_name,
            description=metadata.description,
            enabled=metadata.enabled and not overridden,
            authentication_type=metadata.authentication_type,
            compatibility_type=metadata.compatibility_type,
            capabilities=sorted(metadata.capabilities, key=lambda c: c.value),
        )

    async def _model_dto(self, metadata: ModelMetadata) -> ModelResponse:
        overridden = await self.overrides.is_model_disabled(
            metadata.provider_id, metadata.model_id
        )
        return ModelResponse(
            provider_id=metadata.provider_id,
            model_id=metadata.model_id,
            display_name=metadata.display_name,
            context_window=metadata.context_window,
            max_output_tokens=metadata.max_output_tokens,
            enabled=metadata.enabled and not overridden,
            capabilities=sorted(metadata.capabilities, key=lambda c: c.value),
        )
