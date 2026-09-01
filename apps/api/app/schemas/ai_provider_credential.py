"""BYOK AI provider credential schemas — write-only.

The raw key is only ever an input (CredentialSet); every response carries
the masked last-4 form only, never the full key.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CredentialSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(..., min_length=1)


class CredentialStatusResponse(BaseModel):
    provider_id: str
    masked_key: str
    updated_at: datetime
    updated_by_email: str | None
