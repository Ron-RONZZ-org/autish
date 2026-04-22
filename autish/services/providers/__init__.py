"""Provider abstractions for backend integrations."""

from autish.services.providers.base import (
    GenerationRequest,
    TextGenerationProvider,
    VerkiProviderError,
)
from autish.services.providers.huggingface import HuggingFaceProvider

__all__ = [
    "GenerationRequest",
    "HuggingFaceProvider",
    "TextGenerationProvider",
    "VerkiProviderError",
]

