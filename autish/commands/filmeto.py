"""filmeto — low-stimulation video CLI (YouTube-focused)."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError


# Lazy import helpers - patchable via tests

# Module-level cache for lazy imports (tests can patch these)
_youtube_dl_class: type | None = None
_download_error_class: type | None = None

# Backwards compatibility: tests patch these directly
YoutubeDL: type | None = None  # type: ignore[misc,valid-type]
DownloadError: type | None = None  # type: ignore[misc,valid-type]


def _get_youtube_dl_class():
    """Lazy import YoutubeDL. Patch _youtube_dl_class or YoutubeDL in tests."""
    import autish.commands.filmeto as _mod

    # First check backwards-compatible alias (tests patch this)
    if hasattr(_mod, "YoutubeDL") and _mod.YoutubeDL is not None:
        return _mod.YoutubeDL
    # Check module-level cache
    if hasattr(_mod, "_youtube_dl_class") and _mod._youtube_dl_class is not None:
        return _mod._youtube_dl_class
    # Otherwise do lazy import
    from yt_dlp import YoutubeDL

    _mod._youtube_dl_class = YoutubeDL
    return YoutubeDL


def _get_download_error():
    """Lazy import DownloadError. Patch _download_error_class or DownloadError in tests."""
    import autish.commands.filmeto as _mod

    # First check backwards-compatible alias (tests patch this)
    if hasattr(_mod, "DownloadError") and _mod.DownloadError is not None:
        return _mod.DownloadError
    # Check module-level cache
    if hasattr(_mod, "_download_error_class") and _mod._download_error_class is not None:
        return _mod._download_error_class
    # Otherwise do lazy import
    from yt_dlp.utils import DownloadError

    _mod._download_error_class = DownloadError
    return DownloadError

    _mod._download_error_class = DownloadError
    return DownloadError


app = typer.Typer(
    name="filmeto",
    help="Filmeto — trankvila navigado de filmetoj (nun: YouTube).",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)

console = Console()
_DATA_DIR: Path = Path.home() / ".local" / "share" / "autish"
_CACHE_FILE: Path = _DATA_DIR / "filmeto_cache.json"
_CONFIG_FILE: Path = _DATA_DIR / "filmeto_agordo.json"
_SEARCH_STRATEGY_FILE: Path = _DATA_DIR / "filmeto_search_strategy.json"
_LARGE_SIZE_BYTES = 500 * 1024 * 1024
_BROWSER_FORK_MAP: dict[str, str] = {
    "floorp": "firefox",
    "librewolf": "firefox",
    "waterfox": "firefox",
    "zen": "firefox",
    "brave": "chrome",
    "vivaldi": "chrome",
    "chromium": "chrome",
}
_CSV_TRUE_VALUES: frozenset[str] = frozenset({"1", "true"})
_CSV_FALSE_VALUES: frozenset[str] = frozenset({"0", "false"})


def _discover_firefox_style_profiles(browser_hint: str) -> list[str]:
    home = Path.home()
    roots: list[Path] = []
    hint = browser_hint.strip().lower()
    if hint == "floorp":
        roots.append(home / ".floorp")
    elif hint in {"librewolf"}:
        roots.append(home / ".librewolf")
    elif hint in {"waterfox"}:
        roots.append(home / ".waterfox")
    elif hint in {"zen"}:
        roots.append(home / ".zen")
    else:
        roots.append(home / ".mozilla" / "firefox")

    profiles: list[Path] = []
    for root in roots:
        profiles_ini = root / "profiles.ini"
        if profiles_ini.exists():
            try:
                current_section = ""
                values: dict[str, dict[str, str]] = {}
                for raw_line in profiles_ini.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith(";"):
                        continue
                    if line.startswith("[") and line.endswith("]"):
                        current_section = line[1:-1].strip()
                        values.setdefault(current_section, {})
                        continue
                    if "=" not in line or not current_section:
                        continue
                    k, v = line.split("=", 1)
                    values.setdefault(current_section, {})[k.strip()] = v.strip()
                for section, cfg in values.items():
                    if not section.lower().startswith("profile"):
                        continue
                    raw_path = cfg.get("Path", "").strip()
                    if not raw_path:
                        continue
                    is_relative = cfg.get("IsRelative", "1").strip() == "1"
                    candidate = (root / raw_path) if is_relative else Path(raw_path)
                    if (candidate / "cookies.sqlite").exists():
                        profiles.append(candidate)
            except OSError:
                pass
        if root.exists():
            for cookie_db in root.rglob("cookies.sqlite"):
                candidate = cookie_db.parent
                if candidate not in profiles:
                    profiles.append(candidate)
    unique: list[str] = []
    seen: set[str] = set()
    for p in profiles:
        text = str(p)
        if text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def _cookie_browser_candidates(raw: str | None) -> list[tuple[str, ...] | None]:
    if not raw:
        return [None]
    value = raw.strip()
    if not value:
        return [None]
    base = _cookies_from_browser_arg(value)
    candidates: list[tuple[str, ...] | None] = [base]
    if ":" in value:
        browser_raw = value.split(":", 1)[0].strip().lower()
        mapped = _BROWSER_FORK_MAP.get(browser_raw, browser_raw)
        if mapped == "firefox":
            for profile in _discover_firefox_style_profiles(browser_raw):
                spec = (mapped, profile, None, None)
                if spec not in candidates:
                    candidates.append(spec)
        if None not in candidates:
            candidates.append(None)
        return candidates
    browser_raw = value.lower()
    mapped = _BROWSER_FORK_MAP.get(browser_raw, browser_raw)
    if mapped == "firefox":
        for profile in _discover_firefox_style_profiles(browser_raw):
            spec = (mapped, profile, None, None)
            if spec not in candidates:
                candidates.append(spec)
    return candidates


def _load_cache() -> dict[str, str]:
    if not _CACHE_FILE.exists():
        return {}
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_cache(mapping: dict[str, str]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_agordo() -> dict[str, str]:
    if not _CONFIG_FILE.exists():
        return {}
    try:
        raw = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key in ("defauxlta_vojo",):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def _save_agordo(cfg: dict[str, str]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_search_strategy() -> dict[str, Any]:
    if not _SEARCH_STRATEGY_FILE.exists():
        return {}
    try:
        raw = json.loads(_SEARCH_STRATEGY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_search_strategy(strategy: dict[str, Any]) -> None:
    def _json_safe(value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, tuple):
            return [_json_safe(v) for v in value]
        if isinstance(value, list):
            return [_json_safe(v) for v in value]
        if isinstance(value, set):
            return sorted(_json_safe(v) for v in value)
        if isinstance(value, dict):
            return {str(k): _json_safe(v) for k, v in value.items()}
        return str(value)

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _SEARCH_STRATEGY_FILE.write_text(
        json.dumps(_json_safe(strategy), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _matches_query(query: str, text: str, *, regex: bool) -> bool:
    q = str(query or "").strip()
    if not q:
        return True
    t = str(text or "")
    if regex:
        return re.search(q, t) is not None
    ql = q.casefold()
    tl = t.casefold()
    if ql in tl:
        return True
    ratio = SequenceMatcher(None, ql, tl).ratio()
    if ratio >= 0.55:
        return True
    for token in re.split(r"\W+", tl):
        if not token:
            continue
        if SequenceMatcher(None, ql, token).ratio() >= 0.75:
            return True
    return False


def _default_downloads_dir() -> Path:
    home = Path.home()
    preferred = home / "Elŝutujo"
    if preferred.exists():
        return preferred
    xdg = home / "Downloads"
    if xdg.exists():
        return xdg
    return home / "Downloads"


def _auto_js_runtimes() -> dict[str, dict[str, str]] | None:
    runtimes: dict[str, dict[str, str]] = {}
    for runtime, binary in (
        ("deno", "deno"),
        ("node", "node"),
        ("quickjs", "qjs"),
        ("bun", "bun"),
    ):
        path = shutil.which(binary)
        if path:
            runtimes[runtime] = {"path": path}
    return runtimes or None


def _ensure_folder(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.exists():
        if not resolved.is_dir():
            typer.echo(f"Ne estas dosierujo: {resolved}", err=True)
            raise typer.Exit(code=1)
        return resolved
    raw = typer.prompt(
        f"Doserujo ne ekzistas: {resolved}. Ĉu krei ĝin? (j/N)",
        default="n",
    )
    if raw.strip().lower() not in {"j", "jes", "y", "yes"}:
        typer.echo("Nuligita.")
        raise typer.Exit(code=1)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _default_download_dir() -> Path:
    cfg = _load_agordo()
    default_raw = cfg.get("defauxlta_vojo")
    if default_raw:
        return _ensure_folder(Path(default_raw))
    return _ensure_folder(_default_downloads_dir())


def _make_uuid(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:8]


def _entry_url(entry: dict[str, Any]) -> str:
    webpage_url = str(entry.get("webpage_url") or "").strip()
    if webpage_url:
        return webpage_url
    entry_id = str(entry.get("id") or "").strip()
    if entry_id:
        return f"https://www.youtube.com/watch?v={entry_id}"
    return ""


def _cookies_from_browser_arg(raw: str | None) -> tuple[str, ...] | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    if ":" in value:
        browser_raw, profile = value.split(":", 1)
        browser = _BROWSER_FORK_MAP.get(
            browser_raw.strip().lower(), browser_raw.strip().lower()
        )
        profile = profile.strip()
        if profile:
            # yt-dlp tuple is (browser, profile, keyring, container); pass None
            # placeholders so absolute paths are never misread as container names.
            return (browser, profile, None, None)
        return (browser,)
    browser = _BROWSER_FORK_MAP.get(value.lower(), value.lower())
    return (browser,)


def _cookie_help_details() -> str:
    home = Path.home()
    return (
        "Kuketoj helpo:\n"
        "  1) Trovu vian retumilan profilon.\n"
        f"     Floorp (Linux): {home}/.floorp/<profilo>\n"
        f"     Firefox (Linux): {home}/.mozilla/firefox/<profilo>\n"
        "     Konsilo: legu profiles.ini por ĝusta profilo-nomo.\n"
        "  2) Testu kun:\n"
        "     --kuketoj-de-retumilo floorp\n"
        "     aŭ --kuketoj-de-retumilo floorp:/plena/vojo/al/profilo\n"
        "     ekz.: --kuketoj-de-retumilo floorp:/home/vi/.floorp/abc.default-default\n"
        "     (la profilo devas enhavi cookies.sqlite)\n"
        "     Noto: filmeto aŭtomate provas plurajn profilojn por firefox/floorp.\n"
        "  3) CLI-kuketoj-eksporto (preferata):\n"
        "     pip install --user yt-dlp\n"
        "     yt-dlp --cookies-from-browser floorp --cookies /tmp/youtube.cookies.txt --skip-download https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"  # noqa: E501
        "     aŭ kun specifa profilo:\n"
        "     yt-dlp --cookies-from-browser firefox:/home/vi/.floorp/abc.default-default --cookies /tmp/youtube.cookies.txt --skip-download https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"  # noqa: E501
        "     poste uzu: filmeto serci <teksto> --kuketoj /tmp/youtube.cookies.txt\n"
        "  4) Rapida diagnozo (CLI):\n"
        "     ls ~/.floorp\n"
        "     find ~/.floorp -maxdepth 3 -name cookies.sqlite\n"
        "  5) JavaScript-runtime por YouTube (rekomendata):\n"
        "     sudo apt install -y nodejs\n"
        "     (aŭ instalu deno: https://deno.com/)\n"
        "  6) Se la konto uzas apartajn ujojn (containers),\n"
        "     provu retumilan defaŭltan ujon."
    )


@app.command("kuketoj-helpo")
def kuketoj_helpo() -> None:
    """Montri detalajn instrukciojn por YouTube-kuketoj kaj profiloj."""
    typer.echo(_cookie_help_details())


def _build_format_selector(
    *, difino: int | None, sonkvalito: int | None, audio: bool, filmeto: bool
) -> str:
    if audio and filmeto:
        raise ValueError("Uzu nur unu el -A/--audio aŭ -F/--filmeto.")
    if audio:
        if sonkvalito is not None:
            return f"bestaudio[abr<={int(sonkvalito)}]/bestaudio"
        return "bestaudio"
    if filmeto:
        if difino is not None:
            return f"bestvideo[height<={int(difino)}]/bestvideo"
        return "bestvideo"
    if difino is not None:
        return f"best[height<={int(difino)}]/best"
    return "best"


def _extract_entries_for_search(
    seed_query: str,
    *,
    limo: int,
    cookies: str | None = None,
    cookies_from_browser: str | None = None,
) -> list[dict[str, Any]]:
    base_opts: dict[str, Any] = {
        "quiet": True,
        "skip_download": True,
        "no_warnings": True,
        "extract_flat": False,
        "ignoreerrors": True,
        "lazy_playlist": True,
    }
    runtimes = _auto_js_runtimes()
    if runtimes:
        base_opts["js_runtimes"] = runtimes
    opts_candidates: list[dict[str, Any]] = []
    cached = _load_search_strategy()
    cached_opts = cached.get("opts")
    if isinstance(cached_opts, dict):
        opts_candidates.append(dict(cached_opts))
    if cookies:
        with_cookie = dict(base_opts)
        with_cookie["cookiefile"] = cookies
        opts_candidates.append(with_cookie)
    for browser_spec in _cookie_browser_candidates(cookies_from_browser):
        with_browser = dict(base_opts)
        if browser_spec is not None:
            with_browser["cookiesfrombrowser"] = browser_spec
        opts_candidates.append(with_browser)
    if not opts_candidates:
        opts_candidates.append(dict(base_opts))
    query = f"ytsearch{max(1, int(limo))}:{seed_query}"
    last_error: DownloadError | None = None
    pending = list(opts_candidates)
    seen_opts: set[str] = set()
    while pending:
        opts = pending.pop(0)
        opts_key = json.dumps(opts, sort_keys=True, default=str)
        if opts_key in seen_opts:
            continue
        seen_opts.add(opts_key)
        with _get_youtube_dl_class()(opts) as ydl:
            try:
                result = ydl.extract_info(query, download=False)
            except _get_download_error() as exc:
                last_error = exc
                msg = str(exc).lower()
                if (
                    "certificate_verify_failed" in msg
                    or "hostname mismatch" in msg
                    or "certificateverifyerror" in msg
                ) and not opts.get("nocheckcertificate"):
                    retry_opts = dict(opts)
                    retry_opts["nocheckcertificate"] = True
                    pending.append(retry_opts)
                if "requested format is not available" in msg and not opts.get(
                    "extract_flat"
                ):
                    retry_opts = dict(opts)
                    retry_opts["extract_flat"] = True
                    pending.append(retry_opts)
                continue
        entries = []
        for item in list(result.get("entries") or []):
            if not isinstance(item, dict):
                continue
            if str(item.get("availability") or "").lower() in {
                "private",
                "premium_only",
                "subscriber_only",
                "needs_auth",
                "unavailable",
            }:
                continue
            entries.append(item)
        if entries:
            _save_search_strategy(
                {
                    "opts": opts,
                    "source": "search-success",
                }
            )
            return entries
        if not opts.get("nocheckcertificate"):
            retry_opts = dict(opts)
            retry_opts["nocheckcertificate"] = True
            pending.append(retry_opts)
        if opts.get("extract_flat") is False:
            retry_opts = dict(opts)
            retry_opts["extract_flat"] = True
            pending.append(retry_opts)
    if last_error is not None:
        raise last_error
    return []


def _estimate_one_item_size(item: dict[str, Any]) -> int:
    val = item.get("filesize")
    if isinstance(val, int) and val > 0:
        return val
    approx = item.get("filesize_approx")
    if isinstance(approx, int) and approx > 0:
        return approx
    return 0


def _flatten_download_items(info: dict[str, Any]) -> list[dict[str, Any]]:
    entries = info.get("entries")
    if isinstance(entries, list):
        return [e for e in entries if isinstance(e, dict)]
    return [info]


def _estimate_downloads(
    targets: list[str],
    format_selector: str,
    *,
    playlist_limo: int | None = None,
    cookies: str | None = None,
    cookies_from_browser: str | None = None,
) -> tuple[int, int]:
    count = 0
    total = 0
    opts = {
        "quiet": True,
        "skip_download": True,
        "no_warnings": True,
        "format": format_selector,
    }
    runtimes = _auto_js_runtimes()
    if runtimes:
        opts["js_runtimes"] = runtimes
    if playlist_limo is not None:
        opts["playlistend"] = max(1, int(playlist_limo))
    if cookies:
        opts["cookiefile"] = cookies
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = _cookies_from_browser_arg(cookies_from_browser)
    with _get_youtube_dl_class()(opts) as ydl:
        for target in targets:
            try:
                info = ydl.extract_info(target, download=False)
            except _get_download_error():
                continue
            for item in _flatten_download_items(info):
                count += 1
                total += _estimate_one_item_size(item)
    return count, total


def _resolve_targets(targets: list[str]) -> list[str]:
    cache = _load_cache()
    resolved: list[str] = []
    for target in targets:
        if target.startswith(("http://", "https://")):
            resolved.append(target)
            continue
        mapped = cache.get(target)
        if not mapped:
            typer.echo(f"Nekonata UUID aŭ URL: {target}", err=True)
            raise typer.Exit(code=1)
        resolved.append(mapped)
    return resolved


def _normalize_csv_option_name(raw: str) -> str | None:
    normalized = str(raw or "").strip().lower()
    if not normalized:
        return None
    key = normalized.replace("-", "").replace("_", "").replace(" ", "")
    mapping = {
        "celo": "celoj",
        "celoj": "celoj",
        "target": "celoj",
        "targets": "celoj",
        "difino": "difino",
        "rezolucio": "difino",
        "sonkvalito": "sonkvalito",
        "audio": "audio",
        "filmeto": "filmeto",
        "limo": "limo",
        "kuketoj": "kuketoj",
        "kuketojderetumilo": "kuketoj_de_retumilo",
        "vojo": "vojo",
        "subtitoloj": "subtitoloj",
    }
    return mapping.get(key)


def _csv_effective_cell(raw: object) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.lower() in {"null", "none"}:
        return None
    return text


def _parse_csv_boolean(value: str, *, field: str, row_number: int) -> bool:
    normalized = value.strip().lower()
    if normalized in _CSV_TRUE_VALUES:
        return True
    if normalized in _CSV_FALSE_VALUES:
        return False
    raise ValueError(
        f"CSV vico {row_number}: nevalida boolea valoro por {field!r}: {value!r}."
    )


def _parse_csv_targets(value: str) -> list[str]:
    return [token for token in re.split(r"[,\s;]+", value.strip()) if token]


def _parse_elsuti_csv_rows(
    csv_path: Path,
    *,
    initial_state: dict[str, object],
) -> list[dict[str, object]]:
    if not csv_path.exists() or not csv_path.is_file():
        raise ValueError(f"CSV-dosiero ne trovita: {csv_path}")
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        mapped_headers: dict[str, str] = {}
        for header in headers:
            option_name = _normalize_csv_option_name(header)
            if option_name:
                mapped_headers[header] = option_name
        if not any(name == "celoj" for name in mapped_headers.values()):
            raise ValueError(
                "CSV-dosiero devas enhavi kolumnon 'celoj' "
                "(ekzemplo: celoj,vojo,audio)."
            )
        state: dict[str, object] = dict(initial_state)
        rows: list[dict[str, object]] = []
        for row_number, row in enumerate(reader, start=2):
            if not isinstance(row, dict):
                continue
            for raw_header, option_name in mapped_headers.items():
                cell = _csv_effective_cell(row.get(raw_header))
                if cell is None:
                    continue
                if option_name == "celoj":
                    parsed_targets = _parse_csv_targets(cell)
                    if not parsed_targets:
                        raise ValueError(
                            f"CSV vico {row_number}: malplena aŭ nevalida 'celoj'."
                        )
                    state["celoj"] = parsed_targets
                elif option_name in {"audio", "filmeto"}:
                    state[option_name] = _parse_csv_boolean(
                        cell, field=option_name, row_number=row_number
                    )
                elif option_name in {"difino", "sonkvalito", "limo"}:
                    try:
                        state[option_name] = int(cell)
                    except ValueError as exc:
                        raise ValueError(
                            f"CSV vico {row_number}: nevalida nombro por "
                            f"{option_name!r}: {cell!r}."
                        ) from exc
                elif option_name == "vojo":
                    state[option_name] = Path(cell)
                else:
                    state[option_name] = cell
            effective_targets = state.get("celoj")
            if not isinstance(effective_targets, list) or not effective_targets:
                raise ValueError(
                    f"CSV vico {row_number}: mankas valida 'celoj' "
                    "(neniu antaŭa valoro por transpreni)."
                )
            rows.append(
                {
                    "celoj": list(effective_targets),
                    "difino": state.get("difino"),
                    "sonkvalito": state.get("sonkvalito"),
                    "audio": bool(state.get("audio", False)),
                    "filmeto": bool(state.get("filmeto", False)),
                    "limo": state.get("limo"),
                    "kuketoj": state.get("kuketoj"),
                    "kuketoj_de_retumilo": state.get("kuketoj_de_retumilo"),
                    "vojo": state.get("vojo"),
                    "subtitoloj": state.get("subtitoloj"),
                }
            )
    return rows


def _pick_closest_format_selector(
    info: dict[str, Any],
    *,
    difino: int | None,
    sonkvalito: int | None,
    audio: bool,
    filmeto: bool,
) -> str:
    formats = [f for f in (info.get("formats") or []) if isinstance(f, dict)]
    if not formats:
        return _build_format_selector(
            difino=difino, sonkvalito=sonkvalito, audio=audio, filmeto=filmeto
        )
    if audio:
        target = int(sonkvalito or 128)
        best = min(
            (
                (abs(int(f.get("abr") or 0) - target), str(f.get("format_id") or ""))
                for f in formats
                if f.get("vcodec") == "none" and f.get("format_id")
            ),
            default=None,
        )
        return best[1] if best and best[1] else "bestaudio"
    if filmeto:
        target = int(difino or 720)
        best = min(
            (
                (abs(int(f.get("height") or 0) - target), str(f.get("format_id") or ""))
                for f in formats
                if f.get("acodec") == "none" and f.get("format_id")
            ),
            default=None,
        )
        return best[1] if best and best[1] else "bestvideo"
    if difino is not None:
        target = int(difino)
        best = min(
            (
                (abs(int(f.get("height") or 0) - target), str(f.get("format_id") or ""))
                for f in formats
                if f.get("format_id")
            ),
            default=None,
        )
        return best[1] if best and best[1] else f"best[height<={target}]/best"
    return "best"


def _resolve_output_template(output_path: Path) -> tuple[Path, str]:
    expanded = output_path.expanduser().resolve()
    if expanded.exists() and expanded.is_dir():
        return expanded, "%(title).80s [%(id)s].%(ext)s"
    if not expanded.exists() and str(output_path).endswith("/"):
        expanded.mkdir(parents=True, exist_ok=True)
        return expanded, "%(title).80s [%(id)s].%(ext)s"
    if (
        not expanded.exists()
        and output_path.suffix == ""
        and output_path.name != ""
        and len(output_path.parts) > 1
    ):
        return expanded, "%(title).80s [%(id)s].%(ext)s"
    parent = expanded.parent
    parent.mkdir(parents=True, exist_ok=True)
    base = expanded.stem if expanded.suffix else expanded.name
    return parent, f"{base}.%(ext)s"


def _format_duration(seconds: Any) -> str:
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return "-"
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _render_clickable_path(path: Path) -> Text:
    resolved = path.expanduser().resolve()
    rendered = str(resolved)
    text = Text(rendered)
    text.stylize(f"link {resolved.as_uri()}")
    return text


def _collect_download_plan(
    targets: list[str],
    format_selector: str,
    *,
    playlist_limo: int | None = None,
    cookies: str | None = None,
    cookies_from_browser: str | None = None,
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    opts = {
        "quiet": True,
        "skip_download": True,
        "no_warnings": True,
        "format": format_selector,
    }
    runtimes = _auto_js_runtimes()
    if runtimes:
        opts["js_runtimes"] = runtimes
    if playlist_limo is not None:
        opts["playlistend"] = max(1, int(playlist_limo))
    if cookies:
        opts["cookiefile"] = cookies
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = _cookies_from_browser_arg(cookies_from_browser)
    with _get_youtube_dl_class()(opts) as ydl:
        for target in targets:
            try:
                info = ydl.extract_info(target, download=False)
            except _get_download_error():
                continue
            for item in _flatten_download_items(info):
                size_bytes = _estimate_one_item_size(item)
                plan.append(
                    {
                        "title": str(item.get("title") or "-"),
                        "duration": _format_duration(item.get("duration")),
                        "author": str(
                            item.get("uploader") or item.get("channel") or "-"
                        ),
                        "size_bytes": size_bytes,
                        "raw": item,
                    }
                )
    return plan


def _destination_path_for_item(
    item: dict[str, Any], output_dir: Path, outtmpl_name: str
) -> Path:
    opts = {
        "quiet": True,
        "skip_download": True,
        "outtmpl": str(output_dir / outtmpl_name),
    }
    with _get_youtube_dl_class()(opts) as ydl:
        prepared = ydl.prepare_filename(item)
    return Path(prepared).expanduser().resolve()


def _download_plan_table(
    plan: list[dict[str, Any]], output_dir: Path, outtmpl_name: str
) -> Table:
    table = Table(title=f"Elŝuta resumo ({len(plan)})")
    table.add_column("Titolo")
    table.add_column("Daŭro", width=10)
    table.add_column("Aŭtoro", width=20)
    table.add_column("Grandeco", width=10)
    table.add_column("Celo", overflow="fold")
    for row in plan:
        item = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        destination = _destination_path_for_item(item or {}, output_dir, outtmpl_name)
        table.add_row(
            str(row.get("title") or "-"),
            str(row.get("duration") or "-"),
            str(row.get("author") or "-"),
            _format_size(int(row.get("size_bytes") or 0)),
            _render_clickable_path(destination),
        )
    return table


def _resolve_download_destination(vojo: Path | None) -> tuple[Path, str]:
    if vojo is not None:
        resolved_output_path = vojo.expanduser()
        if not resolved_output_path.is_absolute():
            resolved_output_path = _default_download_dir() / resolved_output_path
        output_dir, outtmpl_name = _resolve_output_template(resolved_output_path)
    else:
        output_dir, outtmpl_name = (
            _default_download_dir(),
            "%(title).80s [%(id)s].%(ext)s",
        )
    return _ensure_folder(output_dir), outtmpl_name


def _run_download(
    targets: list[str],
    output_dir: Path,
    format_selector: str,
    *,
    playlist_limo: int | None = None,
    cookies: str | None = None,
    cookies_from_browser: str | None = None,
    outtmpl_name: str = "%(title).80s [%(id)s].%(ext)s",
    subtitles: str | None = None,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": False,
        "format": format_selector,
        "outtmpl": str(output_dir / outtmpl_name),
    }
    runtimes = _auto_js_runtimes()
    if runtimes:
        opts["js_runtimes"] = runtimes
    if playlist_limo is not None:
        opts["playlistend"] = max(1, int(playlist_limo))
    if cookies:
        opts["cookiefile"] = cookies
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = _cookies_from_browser_arg(cookies_from_browser)
    if subtitles:
        spec = subtitles.strip().lower()
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = spec in {"auto", "all"}
        if spec not in {"auto", "all"}:
            langs = [x.strip() for x in subtitles.split(",") if x.strip()]
            if langs:
                opts["subtitleslangs"] = langs
        opts["subtitlesformat"] = "best"
    created: list[Path] = []
    with _get_youtube_dl_class()(opts) as ydl:
        for target in targets:
            before = {p for p in output_dir.iterdir() if p.is_file()}
            ydl.extract_info(target, download=True)
            after = {p for p in output_dir.iterdir() if p.is_file()}
            new_files = sorted(after - before, key=lambda p: p.name)
            created.extend(new_files)
    return created


def _format_size(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "nekonata"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def _format_entry_date(entry: dict[str, Any]) -> str:
    upload = str(entry.get("upload_date") or "").strip()
    if len(upload) == 8 and upload.isdigit():
        return f"{upload[:4]}-{upload[4:6]}-{upload[6:]}"
    for field in ("release_date",):
        value = str(entry.get(field) or "").strip()
        if len(value) == 8 and value.isdigit():
            return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    for field in ("timestamp", "release_timestamp"):
        value = entry.get(field)
        if isinstance(value, (int, float)) and value > 0:
            return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d")
    return "-"


def _playlist_table(entries: list[dict[str, Any]], title: str) -> Table:
    table = Table(title=title)
    table.add_column("#", style="dim")
    table.add_column("UUID", style="dim")
    table.add_column("Aŭtoro")
    table.add_column("Titolo")
    table.add_column("Dato")
    for idx, item in enumerate(entries, 1):
        url = _entry_url(item)
        uid = _make_uuid(url or str(item.get("id") or item.get("title") or ""))
        table.add_row(
            str(idx),
            uid,
            str(item.get("uploader") or item.get("channel") or "-"),
            str(item.get("title") or "-"),
            _format_entry_date(item),
        )
    return table


def _print_agordi_summary(cfg: dict[str, str]) -> None:
    table = Table(title="Filmeto-agordoj")
    table.add_column("Agordo", style="dim", width=20)
    table.add_column("Valoro", overflow="fold")
    default_path = cfg.get("defauxlta_vojo") or str(_default_downloads_dir())
    table.add_row("defaŭlta vojo", _render_clickable_path(Path(default_path)))
    console.print(table)


@app.command("agordi")
def agordi(
    vojo: Path | None = typer.Option(
        None,
        "-v",
        "--vojo",
        file_okay=False,
        dir_okay=True,
        resolve_path=False,
        help="Defaŭlta dosierujo por `filmeto elsuti`.",
    ),
) -> None:
    """Montri aŭ agordi defaŭltojn por filmeto."""
    cfg = _load_agordo()
    if vojo is None:
        _print_agordi_summary(cfg)
        return
    chosen = _ensure_folder(vojo)
    cfg["defauxlta_vojo"] = str(chosen)
    _save_agordo(cfg)
    typer.echo(f"Konservis defaŭltan vojon: {chosen}")
    _print_agordi_summary(cfg)


@app.command("agordo", hidden=True)
def agordo(
    vojo: Path | None = typer.Option(
        None,
        "-v",
        "--vojo",
        file_okay=False,
        dir_okay=True,
        resolve_path=False,
        help="Defaŭlta dosierujo por `filmeto elsuti`.",
    ),
) -> None:
    """Malnova aliaso por `filmeto agordi`."""
    agordi(vojo=vojo)


@app.command("serci")
def serci(
    titolo: str = typer.Argument("", help="Serĉteksto en titolo (defaŭlte)."),
    priskribo: str | None = typer.Option(
        None, "-p", "--priskribo", help="Filtri laŭ plena priskribo."
    ),
    fonto: str | None = typer.Option(
        None, "-f", "--fonto", help="Filtri laŭ aŭtoro/kanalo."
    ),
    aldona: bool = typer.Option(
        False, "-a", "--aldona", help="Montri ankaŭ views kaj abonantojn."
    ),
    limo: int = typer.Option(
        20, "-lo", "--limo", min=1, help="Maksimuma nombro de rezultoj."
    ),
    kuketoj: str | None = typer.Option(
        None, "--kuketoj", help="Vojo al cookies.txt por YouTube aŭtentigo."
    ),
    kuketoj_de_retumilo: str | None = typer.Option(
        None,
        "--kuketoj-de-retumilo",
        help=(
            "Browser to import cookies from. Valid values: firefox, floorp, librewolf, waterfox, zen (Firefox-based), "
            "chrome, brave, vivaldi, chromium (Chromium-based). "
            "Example: --kuketoj-de-retumilo firefox"
        ),
    ),
    playlistoj: bool = typer.Option(
        False,
        "--playlistoj",
        help="Serĉi YouTube-playlistojn anstataŭ unuopajn filmetojn.",
    ),
    regex: bool = typer.Option(
        False,
        "-r",
        "--regex",
        help="Uzi POSIX-bazan regex-serĉon por titolo/priskribo/fonto.",
    ),
) -> None:
    """Serĉi YouTube-filmetojn laŭ pluraj kriterioj."""
    seed = titolo or priskribo or fonto or "youtube"
    if playlistoj:
        seed = f"{seed} playlist"
    try:
        entries = _extract_entries_for_search(
            seed,
            limo=limo,
            cookies=kuketoj,
            cookies_from_browser=kuketoj_de_retumilo,
        )
    except _get_download_error() as exc:
        typer.echo(f"Serĉ-eraro: {exc}", err=True)
        typer.echo(
            "Sugesto: uzu --kuketoj aŭ --kuketoj-de-retumilo por YouTube-bot-kontrolo.",
            err=True,
        )
        typer.echo(
            "Ekzemplo por fork: --kuketoj-de-retumilo floorp[:profilo-vojo]",
            err=True,
        )
        typer.echo(_cookie_help_details(), err=True)
        raise typer.Exit(code=1) from exc
    if not entries:
        typer.echo(
            "Neniuj uzeblaj rezultoj (eblaj privataj/neatingeblaj filmetoj).",
            err=True,
        )
        typer.echo(_cookie_help_details(), err=True)
        raise typer.Exit(code=1)
    filtered: list[dict[str, Any]] = []
    playlist_results: list[dict[str, Any]] = []
    try:
        for e in entries:
            etit = str(e.get("title") or "")
            edesc = str(e.get("description") or "")
            eupl = str(e.get("uploader") or e.get("channel") or "")
            if titolo and not _matches_query(titolo, etit, regex=regex):
                continue
            if priskribo and not _matches_query(priskribo, edesc, regex=regex):
                continue
            if fonto and not _matches_query(fonto, eupl, regex=regex):
                continue
            filtered.append(e)
            if len(filtered) >= limo:
                break
    except re.error as exc:
        typer.echo(f"Nevalida regex-esprimo: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if playlistoj:
        playlist_query = f"ytsearch{max(1, int(limo))}:{seed} playlist"
        opts = {"quiet": True, "skip_download": True, "extract_flat": True}
        with _get_youtube_dl_class()(opts) as ydl:
            info = ydl.extract_info(playlist_query, download=False)
        for item in (info.get("entries") or []):
            if not isinstance(item, dict):
                continue
            url = _entry_url(item) or str(item.get("url") or "")
            if "list=" not in url and item.get("_type") not in {"playlist"}:
                continue
            playlist_results.append(item)
    if not filtered:
        if not playlist_results:
            typer.echo("Neniu filmeto trovita.")
            return
    cache = _load_cache()
    table = Table(title=f"Filmeto-serĉo ({len(filtered)})")
    table.add_column("UUID", style="dim")
    table.add_column("Aŭtoro")
    table.add_column("Titolo")
    table.add_column("Dato")
    if aldona:
        table.add_column("Views", justify="right")
        table.add_column("Abonantoj", justify="right")
    for e in filtered:
        url = _entry_url(e)
        uid = _make_uuid(url or str(e.get("id") or e.get("title") or ""))
        if url:
            cache[uid] = url
        date = _format_entry_date(e)
        row = [
            uid,
            str(e.get("uploader") or e.get("channel") or "-"),
            str(e.get("title") or "-"),
            date or "-",
        ]
        if aldona:
            row.append(str(e.get("view_count") or "-"))
            row.append(str(e.get("channel_follower_count") or "-"))
        table.add_row(*row)
    _save_cache(cache)
    console.print(table)
    if playlist_results:
        ptable = Table(title=f"Playlistoj ({len(playlist_results)})")
        ptable.add_column("UUID", style="dim")
        ptable.add_column("Aŭtoro")
        ptable.add_column("Titolo")
        for item in playlist_results:
            url = _entry_url(item) or str(item.get("url") or "")
            uid = _make_uuid(url or str(item.get("id") or item.get("title") or ""))
            if url:
                cache[uid] = url
            ptable.add_row(
                uid,
                str(item.get("uploader") or item.get("channel") or "-"),
                str(item.get("title") or "-"),
            )
        _save_cache(cache)
        console.print(ptable)


@app.command("vidi")
def vidi(
    celoj: list[str] = typer.Argument(..., help="UUID aŭ URL de filmeto(j)."),
    limo: int | None = typer.Option(
        None,
        "-lo",
        "--limo",
        min=1,
        help="Por playlist: elŝuti nur unuajn N elementojn.",
    ),
    kuketoj: str | None = typer.Option(
        None, "--kuketoj", help="Vojo al cookies.txt por YouTube aŭtentigo."
    ),
    kuketoj_de_retumilo: str | None = typer.Option(
        None,
        "--kuketoj-de-retumilo",
        help=(
            "Browser to import cookies from. Valid values: firefox, floorp, librewolf, waterfox, zen (Firefox-based), "
            "chrome, brave, vivaldi, chromium (Chromium-based). "
            "Example: --kuketoj-de-retumilo firefox"
        ),
    ),
) -> None:
    """Elŝuti filmeton al /tmp kaj malfermi en defaŭlta video-ludilo."""
    targets = _resolve_targets(celoj)
    if len(targets) == 1 and "list=" in targets[0]:
        opts = {
            "quiet": True,
            "skip_download": True,
            "extract_flat": True,
            "ignoreerrors": True,
        }
        with _get_youtube_dl_class()(opts) as ydl:
            info = ydl.extract_info(targets[0], download=False)
        entries = [
            e for e in (info.get("entries") or []) if isinstance(e, dict)
        ]
        if not entries:
            typer.echo("Playlisto malplena aŭ neatingebla.", err=True)
            raise typer.Exit(code=1)
        console.print(_playlist_table(entries, "Playlisto"))
        return
    tmp_dir = Path(tempfile.mkdtemp(prefix="autish_filmeto_"))
    try:
        files = _run_download(
            targets,
            tmp_dir,
            "best",
            playlist_limo=limo,
            cookies=kuketoj,
            cookies_from_browser=kuketoj_de_retumilo,
        )
    except _get_download_error() as exc:
        typer.echo(f"Elŝut-eraro: {exc}", err=True)
        typer.echo(
            "Sugesto: uzu --kuketoj aŭ --kuketoj-de-retumilo por YouTube-bot-kontrolo.",
            err=True,
        )
        typer.echo(_cookie_help_details(), err=True)
        raise typer.Exit(code=1) from exc
    if not files:
        typer.echo("Neniu dosiero elŝutita.", err=True)
        raise typer.Exit(code=1)
    for path in files:
        try:
            subprocess.run(["xdg-open", str(path)], check=True)
        except FileNotFoundError as exc:
            typer.echo("xdg-open ne trovita.", err=True)
            raise typer.Exit(code=1) from exc
        except subprocess.CalledProcessError as exc:
            typer.echo(f"Ne povis malfermi: {path}", err=True)
            raise typer.Exit(code=1) from exc
    typer.echo(f"Malfermis {len(files)} filmeto(j)n el: {tmp_dir}")


@app.command("elsuti")
def elsuti(
    celoj: list[str] = typer.Argument(
        [], help="UUID aŭ URL de filmeto(j)/playlist(j). Ekzemplo: abc12345"
    ),
    difino: int | None = typer.Option(
        None, "-d", "--difino", help="Maksimuma video-rezolucio (ekz. 720, 1080)."
    ),
    sonkvalito: int | None = typer.Option(
        None, "-s", "--sonkvalito", help="Maksimuma audio-kvalito (abr kbps)."
    ),
    audio: bool = typer.Option(False, "-A", "--audio", help="Elŝuti nur audio."),
    filmeto: bool = typer.Option(
        False, "-F", "--filmeto", help="Elŝuti nur videon (sen audio)."
    ),
    limo: int | None = typer.Option(
        None,
        "-lo",
        "--limo",
        min=1,
        help="Por playlist: elŝuti nur unuajn N elementojn.",
    ),
    kuketoj: str | None = typer.Option(
        None, "--kuketoj", help="Vojo al cookies.txt por YouTube aŭtentigo."
    ),
    kuketoj_de_retumilo: str | None = typer.Option(
        None,
        "--kuketoj-de-retumilo",
        help=(
            "Browser to import cookies from. Valid values: firefox, floorp, librewolf, waterfox, zen (Firefox-based), "
            "chrome, brave, vivaldi, chromium (Chromium-based). "
            "Example: --kuketoj-de-retumilo firefox"
        ),
    ),
    vojo: Path | None = typer.Option(
        None,
        "-v",
        "--vojo",
        file_okay=False,
        dir_okay=True,
        resolve_path=False,
        help="Cela dosierujo aŭ plena dosiervojo (nomo de elŝuto).",
    ),
    subtitoloj: str | None = typer.Option(
        None,
        "--subtitoloj",
        help="Subtitoloj por elŝuti: auto, all, aŭ listo de lingvoj (ekz. eo,en,fr).",
    ),
    csv_dosiero: Path | None = typer.Option(
        None,
        "--csv-dosiero",
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=False,
        help=(
            "CSV por plurbata elŝuto kun kolumnoj kiel celoj,vojo,audio. "
            "Ekzemplo: --csv-dosiero /tmp/elsutoj.csv"
        ),
    ),
) -> None:
    """Elŝuti filmetojn/playlistojn kun difinita kvalito.

    Notoj:
    - Se --difino/--sonkvalito ne ekzakte kongruas, sistemo elektas plej proksiman
      haveblan formaton.
    - Proksimuma datuma uzo por filmeto:
      480p ≈ 8-15 MB/min, 720p ≈ 15-35 MB/min, 1080p ≈ 35-80 MB/min.
      480p por voĉo/kursoj, 720p por ĝenerala uzo, 1080p por detalaj bildoj.
    """
    if not celoj and csv_dosiero is None:
        typer.echo("Mankas celo(j): uzu argumenton CELOJ aŭ --csv-dosiero.", err=True)
        raise typer.Exit(code=1)

    initial_state: dict[str, object] = {
        "celoj": list(celoj),
        "difino": difino,
        "sonkvalito": sonkvalito,
        "audio": audio,
        "filmeto": filmeto,
        "limo": limo,
        "kuketoj": kuketoj,
        "kuketoj_de_retumilo": kuketoj_de_retumilo,
        "vojo": vojo,
        "subtitoloj": subtitoloj,
    }
    if csv_dosiero is not None:
        try:
            specs = _parse_elsuti_csv_rows(csv_dosiero, initial_state=initial_state)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
    else:
        specs = [initial_state]

    if not specs:
        typer.echo("Neniu elŝuta vico trovita en CSV.", err=True)
        raise typer.Exit(code=1)

    jobs: list[dict[str, object]] = []
    for index, spec in enumerate(specs, start=1):
        row_difino = spec.get("difino")
        row_sonkvalito = spec.get("sonkvalito")
        row_audio = bool(spec.get("audio", False))
        row_filmeto = bool(spec.get("filmeto", False))
        row_limo = spec.get("limo")
        row_kuketoj = str(spec.get("kuketoj") or "") or None
        row_browser = str(spec.get("kuketoj_de_retumilo") or "") or None
        row_subtitoloj = str(spec.get("subtitoloj") or "") or None
        row_vojo_raw = spec.get("vojo")
        row_vojo = row_vojo_raw if isinstance(row_vojo_raw, Path) else None
        row_targets_raw = spec.get("celoj") or []
        row_targets = [str(item) for item in row_targets_raw if str(item).strip()]
        if not row_targets:
            typer.echo(f"Vico {index}: mankas celo(j).", err=True)
            raise typer.Exit(code=1)
        try:
            format_selector = _build_format_selector(
                difino=int(row_difino) if isinstance(row_difino, int) else None,
                sonkvalito=(
                    int(row_sonkvalito) if isinstance(row_sonkvalito, int) else None
                ),
                audio=row_audio,
                filmeto=row_filmeto,
            )
        except ValueError as exc:
            typer.echo(f"Vico {index}: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        targets = _resolve_targets(row_targets)
        output_dir, outtmpl_name = _resolve_download_destination(row_vojo)
        try:
            plan = _collect_download_plan(
                targets,
                format_selector,
                playlist_limo=int(row_limo) if isinstance(row_limo, int) else None,
                cookies=row_kuketoj,
                cookies_from_browser=row_browser,
            )
        except _get_download_error() as exc:
            typer.echo(f"Taks-eraro (vico {index}): {exc}", err=True)
            typer.echo(
                "Sugesto: uzu --kuketoj aŭ --kuketoj-de-retumilo por "
                "YouTube-bot-kontrolo.",
                err=True,
            )
            typer.echo(_cookie_help_details(), err=True)
            raise typer.Exit(code=1) from exc
        jobs.append(
            {
                "index": index,
                "targets": targets,
                "difino": int(row_difino) if isinstance(row_difino, int) else None,
                "sonkvalito": (
                    int(row_sonkvalito) if isinstance(row_sonkvalito, int) else None
                ),
                "audio": row_audio,
                "filmeto": row_filmeto,
                "limo": int(row_limo) if isinstance(row_limo, int) else None,
                "kuketoj": row_kuketoj,
                "kuketoj_de_retumilo": row_browser,
                "subtitoloj": row_subtitoloj,
                "output_dir": output_dir,
                "outtmpl_name": outtmpl_name,
                "format_selector": format_selector,
                "plan": plan,
            }
        )

    count = sum(len(job.get("plan") or []) for job in jobs)
    total = sum(
        int(item.get("size_bytes") or 0)
        for job in jobs
        for item in (job.get("plan") or [])
    )
    typer.echo(f"Taksita nombro de elŝutoj: {count}")
    typer.echo(f"Taksita grandeco: {_format_size(total)}")
    for job in jobs:
        plan = job.get("plan") or []
        if len(jobs) > 1:
            typer.echo(
                f"Vico {job.get('index')} — {len(job.get('targets') or [])} celo(j):"
            )
        if plan:
            console.print(
                _download_plan_table(
                    plan,
                    Path(job["output_dir"]),
                    str(job["outtmpl_name"]),
                )
            )
    raw = typer.prompt("Ĉu daŭrigi elŝuton? (J/n)", default="J")
    if raw.strip().lower()[:1] in {"n"}:
        typer.echo("Nuligita.")
        return

    downloaded_total = 0
    for job in jobs:
        job_index = int(job.get("index") or 0)
        targets = list(job.get("targets") or [])
        format_selector = str(job.get("format_selector") or "best")
        row_difino = job.get("difino")
        row_sonkvalito = job.get("sonkvalito")
        row_audio = bool(job.get("audio", False))
        row_filmeto = bool(job.get("filmeto", False))
        try:
            if row_difino is not None or row_sonkvalito is not None:
                probe_opts = {
                    "quiet": True,
                    "skip_download": True,
                    "extract_flat": False,
                }
                with YoutubeDL(probe_opts) as ydl:
                    probe = ydl.extract_info(targets[0], download=False)
                format_selector = _pick_closest_format_selector(
                    probe,
                    difino=int(row_difino) if isinstance(row_difino, int) else None,
                    sonkvalito=(
                        int(row_sonkvalito)
                        if isinstance(row_sonkvalito, int)
                        else None
                    ),
                    audio=row_audio,
                    filmeto=row_filmeto,
                )
            files = _run_download(
                targets,
                Path(job["output_dir"]),
                format_selector,
                playlist_limo=(
                    int(job["limo"]) if isinstance(job.get("limo"), int) else None
                ),
                cookies=str(job.get("kuketoj") or "") or None,
                cookies_from_browser=str(job.get("kuketoj_de_retumilo") or "") or None,
                outtmpl_name=str(job["outtmpl_name"]),
                subtitles=str(job.get("subtitoloj") or "") or None,
            )
            downloaded_total += len(files)
        except _get_download_error() as exc:
            prefix = f" (vico {job_index})" if job_index else ""
            typer.echo(f"Elŝut-eraro{prefix}: {exc}", err=True)
            typer.echo(
                "Sugesto: uzu --kuketoj aŭ --kuketoj-de-retumilo por "
                "YouTube-bot-kontrolo.",
                err=True,
            )
            typer.echo(_cookie_help_details(), err=True)
            raise typer.Exit(code=1) from exc
    typer.echo(f"Sukcese elŝutis {downloaded_total} dosieron(j)n.")
