"""AI management schemas — safe discovery DTOs.

Never serialize credentials, base URLs, or registry internals.
"""

from pydantic import BaseModel

from app.ai.capabilities import AICapability


class ProviderResponse(BaseModel):
    provider_id: str
    display_name: str
    description: str
    enabled: bool
    authentication_type: str
    compatibility_type: str
    capabilities: list[AICapability]


class ModelResponse(BaseModel):
    provider_id: str
    model_id: str
    display_name: str
    context_window: int
    max_output_tokens: int
    enabled: bool
    capabilities: list[AICapability]
