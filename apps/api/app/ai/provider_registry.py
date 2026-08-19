"""Provider registry — provider_id string → AIProvider instance."""

from app.ai.exceptions import AIProviderUnavailableError


class DuplicateProviderError(Exception):
    pass


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, object] = {}

    def register(self, provider: object) -> None:
        provider_id = provider.metadata.provider_id
        if provider_id in self._providers:
            raise DuplicateProviderError(f"provider already registered: {provider_id}")
        self._providers[provider_id] = provider

    def get(self, provider_id: str) -> object:
        provider = self._providers.get(provider_id)
        if provider is None:
            raise AIProviderUnavailableError(f"unknown provider: {provider_id}")
        return provider

    def list(self) -> list[object]:
        return list(self._providers.values())

    def exists(self, provider_id: str) -> bool:
        return provider_id in self._providers
