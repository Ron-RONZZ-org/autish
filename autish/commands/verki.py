"""verki — AI-helpita verkado kaj reskribo."""

from __future__ import annotations

import os
import pyperclip
from pathlib import Path

import typer

from autish.commands import kunteksto
from autish.commands.kp import _copy as _kp_copy
from autish.commands.uzanto import _load_profile
from autish.services.providers.huggingface import HuggingFaceProvider
from autish.services.verki import VerkiRequest, VerkiService, VerkiServiceError

app = typer.Typer(
    name="verki",
    help="Verki — AI-helpita generado kaj reskribo de teksto.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)

# Add kunteksto subcommand
app.add_typer(kunteksto.app, name="kunteksto")

_VALIDAJ_LONGOJ = frozenset({"mallonga", "normala", "longa"})


def _read_text_file(path: Path) -> str:
    if not path.exists():
        raise ValueError(f"Dosiero ne trovita: {path}")
    if path.is_dir():
        raise ValueError(f"Atendita dosiero, sed ricevis dosierujon: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Ne povis legi dosieron {path}: {exc}") from exc


def _resolve_text_input(
    *,
    inline_value: str | None,
    file_path: Path | None,
    label: str,
) -> str | None:
    if inline_value is not None and file_path is not None:
        raise ValueError(f"Uzu nur unu fonton por {label}: teksto aŭ dosiero.")
    if file_path is not None:
        return _read_text_file(file_path)
    return inline_value


def _resolve_hf_token(explicit_token: str | None) -> str | None:
    # Check explicit token first
    if explicit_token and explicit_token.strip():
        return explicit_token.strip()
    # Check environment variables
    for env_name in ("HF_TOKEN", "HUGGINGFACE_API_TOKEN"):
        value = os.getenv(env_name)
        if value and value.strip():
            return value.strip()
    # Check user profile
    try:
        profile = _load_profile(quiet=True)
        if profile and "api_slosilo_huggingface" in profile:
            value = profile["api_slosilo_huggingface"]
            if value and value.strip():
                return value.strip()
    except (KeyError, TypeError):
        pass
    return None


def _build_verki_service(
    *,
    provizanto: str,
    modelo: str,
    api_slosilo: str | None,
) -> VerkiService:
    provider_name = provizanto.strip().lower()
    if provider_name != "huggingface":
        raise ValueError("Nesubtenata provizanto. Nuntempe subtenata: huggingface.")
    token = _resolve_hf_token(api_slosilo)
    if not token:
        raise ValueError(
            "Mankas API-slosilo por Hugging Face. Uzu --api-slosilo aŭ agordu "
            "HF_TOKEN/HUGGINGFACE_API_TOKEN aŭ en uzanto profilo."
        )
    provider = HuggingFaceProvider(model=modelo, token=token)
    return VerkiService(provider=provider)


@app.command("generi")
def generi(
    instrukcio: str | None = typer.Option(
        None,
        "-i",
        "--instrukcio",
        help=(
            "Kion fari kun la teksto "
            "(ekz. --instrukcio 'Reskribu por pli formala tono')."
        ),
    ),
    teksto: str | None = typer.Option(
        None,
        "-t",
        "--teksto",
        help=(
            "Fonta teksto por reskribo (ekz. --teksto 'Mi volas pli klaran version.')."
        ),
    ),
    teksto_dosiero: Path | None = typer.Option(
        None,
        "-td",
        "--teksto-dosiero",
        help="Vojo al fonta teksto-dosiero (ekz. -td ./malneto.txt).",
    ),
    tono: str | None = typer.Option(
        None,
        "-to",
        "--tono",
        help="Cela tono (ekz. --tono trankvila).",
    ),
    longo: str | None = typer.Option(
        None,
        "-lo",
        "--longo",
        help=(
            "Target text length. Valid values: mallonga (short), "
            "normala (normal), longa (long). Example: -lo mallonga"
        ),
    ),
    registro: str | None = typer.Option(
        None,
        "-r",
        "--registro",
        help="Cela registro (ekz. --registro formala).",
    ),
    stilo: str | None = typer.Option(
        None,
        "-s",
        "--stilo",
        help="Priskribo de persona stilo (ekz. -s 'simpla kaj rekta').",
    ),
    stilo_ekzemplo: str | None = typer.Option(
        None,
        "-se",
        "--stilo-ekzemplo",
        help="Malloga stilo-provo (ekz. -se 'Mi uzas klarajn frazojn.').",
    ),
    stilo_dosiero: Path | None = typer.Option(
        None,
        "-sd",
        "--stilo-dosiero",
        help=("Vojo al dosiero kun persona stilo-provo (ekz. -sd ./mia_stilo.txt)."),
    ),
    kunteksto_dosiero: Path | None = typer.Option(
        None,
        "-Kd",
        "--kunteksto-dosiero",
        help="Vojo al aldona kunteksto (ekz. -Kd ./kunteksto.md).",
    ),
    kunteksto_uuid: str | None = typer.Option(
        None,
        "-K",
        "--kunteksto",
        help="UUID de verki kunteksto-eniro (ekz. -K a1b2c3d4).",
    ),
    kopii: bool = typer.Option(
        False,
        "-k",
        "--kopii",
        help="Kopii la rezulton al la sistema tondujo (clipboard).",
    ),
    eksporti: Path | None = typer.Option(
        None,
        "-E",
        "--eksporti",
        help="Eksporti la rezulton al dosiero (kreos parent-dosierojn).",
    ),
    modelo: str = typer.Option(
        "google/flan-t5-base",
        "-m",
        "--modelo",
        help="Hugging Face modelo (ekz. -m google/flan-t5-base).",
    ),
    provizanto: str = typer.Option(
        "huggingface",
        "-p",
        "--provizanto",
        help="AI-provizanto (ekz. -p huggingface).",
    ),
    api_slosilo: str | None = typer.Option(
        None,
        "-a",
        "--api-slosilo",
        help="API-slosilo (ekz. -a hf_xxxxx).",
    ),
    maksimumaj_tokenoj: int = typer.Option(
        512,
        "-mt",
        "--maksimumaj-tokenoj",
        help="Maksimuma nombro de novaj tokenoj (ekz. -mt 300).",
    ),
    temperaturo: float = typer.Option(
        0.7,
        "-tm",
        "--temperaturo",
        help="Kreema grado inter 0 kaj 2 (ekz. -tm 0.4).",
    ),
) -> None:
    """Generate or rewrite text with AI."""
    if not instrukcio:
        typer.echo("Eraro: --instrukcio estas deviga.", err=True)
        raise typer.Exit(code=1)
    try:
        source_text = _resolve_text_input(
            inline_value=teksto,
            file_path=teksto_dosiero,
            label="fonta teksto",
        )
        style_example = _resolve_text_input(
            inline_value=stilo_ekzemplo,
            file_path=stilo_dosiero,
            label="stilo-ekzemplo",
        )
        if longo is not None and longo.strip().lower() not in _VALIDAJ_LONGOJ:
            validaj = ", ".join(sorted(_VALIDAJ_LONGOJ))
            raise ValueError(f"Nevalida --longo valoro. Uzu unu el: {validaj}.")
        
        # Resolve context: either from file or from kunteksto database
        context = None
        if kunteksto_dosiero and kunteksto_uuid:
            raise ValueError("Uzu nur unu fonton por kunteksto: dosiero aŭ UUID.")
        if kunteksto_dosiero:
            context = _read_text_file(kunteksto_dosiero)
        elif kunteksto_uuid:
            # Load context from kunteksto database
            entry = kunteksto._find_by_uuid(kunteksto_uuid)
            if not entry:
                raise ValueError(f"Kunteksto ne trovita: {kunteksto_uuid}")
            context = entry.get("enhavo")
        
        service = _build_verki_service(
            provizanto=provizanto,
            modelo=modelo,
            api_slosilo=api_slosilo,
        )
        request = VerkiRequest(
            instrukcio=instrukcio,
            fonta_teksto=source_text,
            tono=tono,
            longo=longo.lower().strip() if longo else None,
            registro=registro,
            stilo=stilo,
            stilo_ekzemplo=style_example,
            kunteksto=context,
            maksimumaj_tokenoj=maksimumaj_tokenoj,
            temperaturo=temperaturo,
        )
        output = service.verki(request)
    except (ValueError, VerkiServiceError) as exc:
        typer.echo(f"Eraro: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    # Export to file if requested
    if eksporti:
        target = Path(eksporti)
        if target.is_dir():
            target = target / "verki_output.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output, encoding="utf-8")
        typer.echo(f"[v] Skribita al {target}", err=True)

    # Copy to clipboard if requested
    if kopii:
        try:
            _kp_copy(output)
        except (pyperclip.PyperclipException, OSError) as exc:
            typer.echo(f"[!] Ne povis kopii al tondujo: {exc}", err=True)

    typer.echo(output)


@app.command("modelo")
def modelo(
    nomo: str | None = typer.Option(
        None,
        "-n",
        "--nomo",
        help="Serĉi modelon laŭ nomo (ekz. -n flan-t5).",
    ),
    provizanto: str = typer.Option(
        "huggingface",
        "-p",
        "--provizanto",
        help="AI-provizanto (ekz. -p huggingface).",
    ),
    api_slosilo: str | None = typer.Option(
        None,
        "-a",
        "--api-slosilo",
        help="API-slosilo (ekz. -a hf_xxxxx).",
    ),
    limigo: int = typer.Option(
        50,
        "-L",
        "--limigo",
        help="Maksimuma nombro da rezultoj (ekz. -L 5).",
    ),
) -> None:
    """Browse available models from the provider."""
    provider_name = provizanto.strip().lower()
    if provider_name != "huggingface":
        typer.echo(
            "Eraro: Nuntempe nur huggingface estas subtenata.",
            err=True,
        )
        raise typer.Exit(code=1)

    token = _resolve_hf_token(api_slosilo)
    if not token:
        typer.echo(
            "Eraro: Mankas API-slosilo. Uzu -a aŭ agordu HF_TOKEN/uzanto profilo.",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        provider = HuggingFaceProvider(model="dummy", token=token)
        models = provider.list_models(query=nomo, limit=limigo)
        if not models:
            typer.echo("Neniuj modeloj trovitaj.")
            return
        for model_id in models:
            typer.echo(model_id)
    except (KeyError, TypeError, Exception) as exc:
        typer.echo(f"Eraro dum listigado: {exc}", err=True)
        raise typer.Exit(code=1) from exc
