"""Provider contracts for verki text generation backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class VerkiProviderError(RuntimeError):
    """Raised when an AI provider call fails."""


@dataclass(frozen=True)
class GenerationRequest:
    """Normalized backend request payload for text generation."""

    prompt: str
    max_new_tokens: int = 512
    temperature: float = 0.7


class TextGenerationProvider(Protocol):
    """Small provider contract used by verki services."""

    def generate(self, request: GenerationRequest) -> str:
        """Generate text from a normalized request."""

