"""AI management service — read-only discovery over the registries.

Router stays thin; all registry access and validation lives here.
"""

from app.ai.metadata import ModelMetadata, ProviderMetadata
from app.ai.model_registry import ModelRegistry
from app.ai.provider_registry import ProviderRegistry
from app.schemas.ai_management import ModelResponse, ProviderResponse


class ProviderNotFoundError(Exception):
    pass


class ModelNotFoundError(Exception):
    pass


class AIManagementService:
    def __init__(self, providers: ProviderRegistry, models: ModelRegistry) -> None:
        self.providers = providers
        self.models = models

    def list_providers(self) -> list[ProviderResponse]:
        return [self._provider_dto(p.metadata) for p in self.providers.list()]

    def get_provider(self, provider_id: str) -> ProviderResponse:
        if not self.providers.exists(provider_id):
            raise ProviderNotFoundError()
        return self._provider_dto(self.providers.get(provider_id).metadata)

    def list_models(self, provider_id: str) -> list[ModelResponse]:
        if not self.providers.exists(provider_id):
            raise ProviderNotFoundError()
        return [self._model_dto(m) for m in self.models.list(provider_id)]

    def get_model(self, provider_id: str, model_id: str) -> ModelResponse:
        if not self.providers.exists(provider_id):
            raise ProviderNotFoundError()
        model = self.models.get(provider_id, model_id)
        if model is None:
            raise ModelNotFoundError()
        return self._model_dto(model)

    @staticmethod
    def _provider_dto(metadata: ProviderMetadata) -> ProviderResponse:
        return ProviderResponse(
            provider_id=metadata.provider_id,
            display_name=metadata.display_name,
            description=metadata.description,
            enabled=metadata.enabled,
            authentication_type=metadata.authentication_type,
            compatibility_type=metadata.compatibility_type,
            capabilities=sorted(metadata.capabilities, key=lambda c: c.value),
        )

    @staticmethod
    def _model_dto(metadata: ModelMetadata) -> ModelResponse:
        return ModelResponse(
            provider_id=metadata.provider_id,
            model_id=metadata.model_id,
            display_name=metadata.display_name,
            context_window=metadata.context_window,
            max_output_tokens=metadata.max_output_tokens,
            enabled=metadata.enabled,
            capabilities=sorted(metadata.capabilities, key=lambda c: c.value),
        )
