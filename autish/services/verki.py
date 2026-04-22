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
        enc_task = ".enc" in instrukcio.lower()

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

        if enc_task:
            lines.extend(
                [
                    "Formato deviga por .enc:",
                    'terminologio.eo="..."',
                    'terminologio.fr="..."',
                    'terminologio.en="..."',
                    'difino.eo="""',
                    "...",
                    '"""',
                    "Respondu nur per valida .enc enhavo.",
                    "Ne uzu ``` kodbarilojn.",
                    "Ne inkluzivu rezonadon, analizajn paŝojn, aŭ antaŭparolojn.",
                ]
            )

        lines.append("Respondu nur per la fina teksto, sen klarigoj aŭ metakomento.")
        return "\n\n".join(lines)

    @staticmethod
    def _normalize_output(text: str, *, enc_task: bool) -> str:
        out = text.strip()
        if enc_task:
            lines = out.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            out = "\n".join(lines).strip()

            marker_positions = [
                pos
                for pos in (
                    out.find("terminologio.eo"),
                    out.find("terminologio.(eo,fr,en)"),
                )
                if pos >= 0
            ]
            if marker_positions:
                out = out[min(marker_positions) :].strip()
        return out

    @staticmethod
    def _is_complete_enc(text: str) -> bool:
        has_terms = (
            (
                "terminologio.eo" in text
                and "terminologio.fr" in text
                and "terminologio.en" in text
            )
            or "terminologio.(eo,fr,en)" in text
        )
        has_definition = "difino.eo" in text
        triple_quote_count = text.count('"""')
        balanced_triple_quotes = triple_quote_count % 2 == 0
        if 'difino.eo="""' in text and triple_quote_count < 2:
            balanced_triple_quotes = False
        return has_terms and has_definition and balanced_triple_quotes

    def verki(self, request: VerkiRequest) -> str:
        if request.maksimumaj_tokenoj <= 0:
            raise VerkiServiceError("maksimumaj-tokenoj devas esti pozitiva entjero.")
        if not (0 <= request.temperaturo <= 2):
            raise VerkiServiceError("temperaturo devas esti inter 0 kaj 2.")

        enc_task = ".enc" in request.instrukcio.lower()
        prompt = self.build_prompt(request)
        max_tokens = request.maksimumaj_tokenoj

        for attempt in range(2):
            generation_request = GenerationRequest(
                prompt=prompt,
                max_new_tokens=max_tokens,
                temperature=request.temperaturo,
                debug_path=request.debug_path,
            )
            try:
                output = self._provider.generate(generation_request)
            except VerkiProviderError as exc:
                raise VerkiServiceError(str(exc)) from exc
            text = self._normalize_output(output, enc_task=enc_task)
            if not text:
                raise VerkiServiceError("La modelo redonis malplenan tekston.")
            if not enc_task or self._is_complete_enc(text):
                return text

            if attempt == 0:
                max_tokens = max(1024, request.maksimumaj_tokenoj * 2)
                prompt = (
                    f"{prompt}\n\n"
                    "La antaŭa respondo estis nekompleta. "
                    "Redonu kompletan kaj validan .enc dosier-tekston."
                )
                continue

        raise VerkiServiceError(
            "La modelo redonis nekompletan .enc enhavon. "
            "Provu pli altan --maksimumaj-tokenoj aŭ alian modelon."
        )
