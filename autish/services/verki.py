"""Business logic for verki text generation and rewriting."""

from __future__ import annotations

from dataclasses import dataclass

from autish.services.providers.base import (
    GenerationRequest,
    TextGenerationProvider,
    VerkiProviderError,
)


class VerkiServiceError(RuntimeError):
    """Raised for user-visible verki service failures."""


@dataclass(frozen=True)
class VerkiRequest:
    """Input model for verki generation and rewrite operations."""

    instrukcio: str
    fonta_teksto: str | None = None
    tono: str | None = None
    longo: str | None = None
    registro: str | None = None
    stilo: str | None = None
    stilo_ekzemplo: str | None = None
    kunteksto: str | None = None
    maksimumaj_tokenoj: int = 512
    temperaturo: float = 0.7
    # Optional path where providers should save raw HTTP response for debugging
    debug_path: str | None = None


class VerkiService:
    """Compose prompts and call backend providers."""

    def __init__(self, provider: TextGenerationProvider) -> None:
        self._provider = provider

    def build_prompt(self, request: VerkiRequest) -> str:
        instrukcio = request.instrukcio.strip()
        if not instrukcio:
            raise VerkiServiceError("Instrukcio ne rajtas esti malplena.")

        lines: list[str] = [
            "Rolo: Vi estas trankvila helpanto por verki kaj redakti tekston.",
            f"Tasko: {instrukcio}",
        ]

        if request.tono:
            lines.append(f"Tono: {request.tono.strip()}")
        if request.longo:
            lines.append(f"Longeco: {request.longo.strip()}")
        if request.registro:
            lines.append(f"Registro: {request.registro.strip()}")
        if request.stilo:
            lines.append(f"Stilo: {request.stilo.strip()}")

        style_example = (request.stilo_ekzemplo or "").strip()
        if style_example:
            lines.append("Persona stilo-ekzemplo (imitu frazritmon kaj vortuzon):")
            lines.append(style_example)

        context = (request.kunteksto or "").strip()
        if context:
            lines.append("Plia kunteksto:")
            lines.append(context)

        source = (request.fonta_teksto or "").strip()
        if source:
            lines.append("Fonta teksto por reskribi:")
            lines.append(source)
        else:
            lines.append("Kreu novan tekston de nulo.")

        lines.append("Respondu nur per la fina teksto, sen klarigoj aŭ metakomento.")
        return "\n\n".join(lines)

    def verki(self, request: VerkiRequest) -> str:
        if request.maksimumaj_tokenoj <= 0:
            raise VerkiServiceError("maksimumaj-tokenoj devas esti pozitiva entjero.")
        if not (0 <= request.temperaturo <= 2):
            raise VerkiServiceError("temperaturo devas esti inter 0 kaj 2.")

        prompt = self.build_prompt(request)
        generation_request = GenerationRequest(
            prompt=prompt,
            max_new_tokens=request.maksimumaj_tokenoj,
            temperature=request.temperaturo,
            debug_path=request.debug_path,
        )
        try:
            output = self._provider.generate(generation_request)
        except VerkiProviderError as exc:
            raise VerkiServiceError(str(exc)) from exc
        text = output.strip()
        if not text:
            raise VerkiServiceError("La modelo redonis malplenan tekston.")
        return text

