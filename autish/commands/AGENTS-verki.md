# AGENTS-verki.md — verki Command Agent Instructions

## Summary
AI-assisted writing and text rewriting using HuggingFace API.

## Purpose and Expected Behavior
- `generi`: Generate text based on prompt (uses HuggingFace API).
- `reskribi`: Rewrite/improve existing text (uses HuggingFace API).
- `instrukcio`: Set or view system instruction for AI context.
- Supports text input from inline argument, file path, or clipboard (`kp` integration).
- Language specification for output: `-l`/`--lingvo`.
- Output length control: `-L`/`--longo` (valid: `mallonga`, `normala`, `longa`).

## Constraints and Invariants
- AI service: `autish.services.verki.VerkiService` with `HuggingFaceProvider`.
- API token resolution order: explicit token → `HF_TOKEN`/`HUGGINGFACE_API_TOKEN` env vars → user profile `api_slosilo_huggingface`.
- Text input resolution: inline text → file path → error if neither.
- Depends on `autish.commands.uzanto._load_profile()` for API key lookup.
- Clipboard integration: `autish.commands.kp._copy()` for copying output.
- Valid lengths: `{"mallonga", "normala", "longa"}` (`_VALIDAJ_LONGOJ`).

## Input/Output Expectations
- Subcommands: `generi`, `reskribi`, `instrukcio`
- Key CLI Options:
  - `generi`/`reskribi`: `[teksto]` (inline text), `-f`/`--dosiero` (file path), `-l`/`--lingvo` (output language), `-L`/`--longo` (length), `-t`/`--token` (API token)
  - `instrukcio`: `[teksto]` (set instruction), `--vidi` (view current)
- Output: Generated/rewritten text (printed to stdout, copied to clipboard)
- Side Effects: Network I/O (HuggingFace API), clipboard write, config file write (instrukcio)

## Documentation Reference
- `docs/man/verki.md`

## Domain-Specific Rules for Agents
- Always use `VerkiService` from `autish.services.verki`; do not call HuggingFace API directly.
- Token resolution: use `_resolve_hf_token()` helper; respects env vars and user profile.
- Text input: use `_resolve_text_input()` helper; mutually exclusive inline/file.
- Error handling: catch `VerkiServiceError`; display user-friendly message via `typer.echo(..., err=True)`.
- Length validation: check against `_VALIDAJ_LONGOJ`; show valid values in help.
- Instruction storage: `~/.local/share/autish/verki_instrukcio.txt` (plain text).
- When adding new AI providers, extend `autish.services.providers` and update `VerkiService`.
