"""Provider-neutral AI error hierarchy.

Adapters translate provider/SDK exceptions into these. Application code and
the gateway never expose SDK exceptions.
"""


class AIError(Exception):
    """Base class for all AI gateway errors."""


class AIProviderError(AIError):
    """Generic provider failure."""


class AIAuthenticationError(AIProviderError):
    """Provider rejected credentials."""


class AIRateLimitError(AIProviderError):
    """Provider rate limit hit."""


class AIInvalidRequestError(AIProviderError):
    """Provider rejected the request as invalid."""


class AIModelNotFoundError(AIProviderError):
    """Provider does not know the requested model."""


class AIProviderUnavailableError(AIProviderError):
    """Provider endpoint unreachable or down."""


class AICapabilityNotSupportedError(AIError):
    """Requested capability is not supported by the model/provider."""
