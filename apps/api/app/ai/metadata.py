"""Provider and model metadata.

Never store API secrets here.
"""

from dataclasses import dataclass, field

from app.ai.capabilities import AICapability


class AuthenticationType(str):
    API_KEY = "api_key"
    NONE = "none"


class CompatibilityType(str):
    OPENAI_COMPATIBLE = "openai_compatible"
    NATIVE = "native"
    FAKE = "fake"


@dataclass(frozen=True)
class ProviderMetadata:
    provider_id: str
    display_name: str
    description: str
    enabled: bool
    base_url: str
    authentication_type: str
    compatibility_type: str
    capabilities: set[AICapability] = field(default_factory=set)


@dataclass(frozen=True)
class ModelMetadata:
    provider_id: str
    model_id: str
    display_name: str
    context_window: int
    max_output_tokens: int
    enabled: bool
    capabilities: set[AICapability] = field(default_factory=set)
