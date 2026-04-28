# AGENTS-shelo.md — shelo Command Agent Instructions

## Summary
Interactive autish shell — run autish commands without typing 'autish' prefix.

## Purpose and Expected Behavior
- Start an interactive REPL-like prompt (`autish>`).
- Accept autish commands directly (e.g., `tempo`, `vorto aldoni ...`).
- Maintain command history via readline (`~/.local/share/autish/shelo_history`).
- Support query result caching — type a number to re-execute a previous query result.
- Exit with `eliru`, `exit`, `q`, or `quit`.

## Constraints and Invariants
- Optional `readline` support (graceful import failure handling).
- History file: `~/.local/share/autish/shelo_history` (max 500 entries).
- `_autish_cmd()` resolves autish executable path (same logic as `kp`).
- `_last_query_results` list for numbered re-execution of previous results.

## Input/Output Expectations
- CLI: `autish shelo` (interactive mode, no subcommands)
- Input: Line-based commands at `autish>` prompt
- Output: Command output printed to terminal
- Side Effects: History file writes, clipboard modifications (if command uses `kp`)

## Documentation Reference
- `docs/man/shelo.md`

## Domain-Specific Rules for Agents
- `invoke_without_command=True` —直接进入交互模式.
- readline integration is optional; always wrap in try/except ImportError.
- Command parsing uses `shlex.split()` for proper quoting support.
- When adding new shell features, preserve minimal/stimulus-free design goal.
- Do not add command completion beyond what readline provides natively.
