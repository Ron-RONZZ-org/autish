"""Provider contracts for verki text generation backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class VerkiProviderError(RuntimeError):
    """Raised when an AI provider call fails."""


@dataclass(frozen=True)
class GenerationRequest:
    """Normalized backend request payload for text generation.

    debug_path: optional path to save raw HTTP response for debugging. When
    provided the provider should write the raw response body (and basic meta)
    to this file. This field is optional and defaults to None.
    """

    prompt: str
    max_new_tokens: int = 512
    temperature: float = 0.7
    debug_path: str | None = None


class TextGenerationProvider(Protocol):
    """Small provider contract used by verki services."""

    def generate(self, request: GenerationRequest) -> str:
        """Generate text from a normalized request."""

