"""Shared AI helpers for command-layer generation flows."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from autish.services.providers.huggingface import HuggingFaceProvider
from autish.services.verki import VerkiService

_AI_CONTEXT_DIR = Path.home() / ".config" / "autish" / "verki"

_DEFAULT_CONTEXTS: dict[str, str] = {
    "verki-generi": (
        "# verki generi — baza kunteksto\n\n"
        "- Restu trankvila, klara, kaj rekta.\n"
        "- Respondu nur per fina rezulto, sen rezonado.\n"
        "- Konservu uzantan stilon kiam stilo-ekzemplo estas donita.\n"
    ),
    "encik-generi": (
        "# encik generi — baza kunteksto\n\n"
        "- Redonu nur validan .enc enhavon.\n"
        "- Produktu nur kampojn `terminologio.xx` kaj `difino.xx`.\n"
        "- Uzu klarajn, hom-legatajn difinojn.\n"
        "- Neniam aldonu antaŭparolon aŭ kodbarilojn.\n"
    ),
    "retposto-analizi": (
        "# retposto analizi — baza kunteksto\n\n"
        "- Traktu la mesaĝojn kiel kuntekste ligitan konversacion.\n"
        "- Resumu klare, kun praktikaj ago-punktoj.\n"
        "- Se petite, elprenu kalendarajn eventojn en valida iCalendar formato.\n"
        "- Neniam inventu faktojn ne ĉeestantajn en la mesaĝoj.\n"
    ),
    "retposto-generi": (
        "# retposto generi — baza kunteksto\n\n"
        "- Verku ĝentilan, klaran, kaj koncizan retpoŝtan malneton.\n"
        "- Uzu la instrukcion kiel ĉefan celon.\n"
        "- Se temo estas donita, kongruigu korpon al tiu temo.\n"
        "- Redonu nur la korpon de la retpoŝto.\n"
    ),
}


def load_ai_context(
    function_name: str, *, override_path: Path | None = None
) -> str | None:
    """Load context text from override or ~/.config/autish/verki/{name}-kunteksto.md.

    If the default context file does not exist yet, it is created with the
    bundled baseline content for that function (when available).
    """
    if override_path is not None:
        if not override_path.exists():
            raise ValueError(f"Kunteksto-dosiero ne trovita: {override_path}")
        if override_path.is_dir():
            raise ValueError(
                f"Atendita kunteksto-dosiero, sed ricevis dosierujon: {override_path}"
            )
        try:
            return override_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(
                f"Ne povis legi kunteksto-dosieron {override_path}: {exc}"
            ) from exc

    _AI_CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    ctx_path = _AI_CONTEXT_DIR / f"{function_name}-kunteksto.md"
    default_text = _DEFAULT_CONTEXTS.get(function_name, "").strip()
    if not ctx_path.exists() and default_text:
        try:
            ctx_path.write_text(default_text + "\n", encoding="utf-8")
        except OSError as exc:
            raise ValueError(
                f"Ne povis krei kunteksto-dosieron {ctx_path}: {exc}"
            ) from exc

    if ctx_path.exists():
        try:
            return ctx_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(
                f"Ne povis legi kunteksto-dosieron {ctx_path}: {exc}"
            ) from exc

    return default_text or None


def resolve_huggingface_token(
    explicit_token: str | None,
    *,
    profile: Mapping[str, object] | None = None,
) -> str | None:
    """Resolve HF token from explicit value, env vars, then profile field."""
    if explicit_token and explicit_token.strip():
        return explicit_token.strip()

    for env_name in ("HF_TOKEN", "HUGGINGFACE_API_TOKEN"):
        value = os.getenv(env_name)
        if value and value.strip():
            return value.strip()

    if profile is not None:
        raw = profile.get("api_slosilo_huggingface")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def build_verki_service(
    *,
    provizanto: str,
    modelo: str,
    api_slosilo: str | None,
    profile: Mapping[str, object] | None = None,
) -> VerkiService:
    """Build a VerkiService instance for supported providers."""
    provider_name = provizanto.strip().lower()
    if provider_name != "huggingface":
        raise ValueError("Nesubtenata provizanto. Nuntempe subtenata: huggingface.")

    token = resolve_huggingface_token(api_slosilo, profile=profile)
    if not token:
        raise ValueError(
            "Mankas API-slosilo por Hugging Face. Uzu --api-slosilo aŭ agordu "
            "HF_TOKEN/HUGGINGFACE_API_TOKEN aŭ en uzanto profilo."
        )
    provider = HuggingFaceProvider(model=modelo, token=token)
    return VerkiService(provider=provider)
