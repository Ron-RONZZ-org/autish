# AGENTS-kp.md — kp Command Agent Instructions

## Summary
Clipboard copy helper — run a command and copy its output to clipboard.

## Purpose and Expected Behavior
- Run any command and copy stdout to clipboard via `pyperclip`.
- Cache output in temp file for retrieval without re-execution (`autish kp` with no args).
- Auto-detect autish subcommands (e.g., `tempo`, `sistemo`) and prepend autish executable path.

## Constraints and Invariants
- Depends on `pyperclip` for clipboard access.
- Cache file: `/tmp/autish_kp_{user}.txt` (via `tempfile.gettempdir()`).
- Known autish subcommands hardcoded in `_AUTISH_SUBCOMMANDS` frozenset.
- `_autish_prefix()` resolves autish executable via `shutil.which()` or falls back to `sys.executable -m autish`.

## Input/Output Expectations
- CLI: `autish kp [command args...]` or bare `autish kp` to retrieve cached output
- Output: Command stdout (copied to clipboard and printed)
- Side Effects: Clipboard modification, temp file write

## Documentation Reference
- `docs/man/kp.md`

## Domain-Specific Rules for Agents
- Always use `_resolve_command()` to prepend autish executable for known subcommands.
- Cache file path uses `getpass.getuser()` for per-user isolation.
- When adding new autish subcommands, update `_AUTISH_SUBCOMMANDS` frozenset.
- `invoke_without_command=True` — bare `autish kp` retrieves cached output.
- Do not add interactive mode; keep as simple command runner + clipboard copy.
