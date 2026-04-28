# AGENTS-wifi.md — wifi Command Agent Instructions

## Summary
Wi-Fi network management via NetworkManager CLI (`nmcli`).

## Purpose and Expected Behavior
- List available/saved Wi-Fi connections with signal strength and security info.
- Connect to a network by SSID (`konekti`).
- Disconnect active Wi-Fi (`malkonekti`).
- Delete saved network profiles (`forigi`).
- Optional password display with `-p` (requires privileges).

## Constraints and Invariants
- Depends on `nmcli` (NetworkManager); Debian/Ubuntu default.
- All subprocess calls wrapped via `_run()` helper; `check=False` to handle errors gracefully.
- No persistent state; read-only system queries and profile management.
- Output via `echo_padded()` from `autish.utils`.

## Input/Output Expectations
- Subcommands: `ls`, `konekti`, `malkonekti`, `forigi`
- CLI Options:
  - `ls`: `[name]` (SSID filter), `-p` (show password), `-k` (show saved profiles)
  - `konekti`: `<name>` (SSID, required)
  - `malkonekti`: no args
  - `forigi`: `<name>` (SSID, required)
- Output: Human-readable tables or connection status messages
- Side Effects: Network connection changes, profile deletion

## Documentation Reference
- `docs/man/wifi.md`

## Domain-Specific Rules for Agents
- Always use `_run()` wrapper for `nmcli` calls; never use bare `subprocess.run()`.
- Active connection listed first in `ls` output.
- Error messages go to stderr via `typer.echo(..., err=True)`.
- nmcli output parsing must handle localized/format variations gracefully.
- Do not add GUI/TUI components; keep CLI-only per global rules.
