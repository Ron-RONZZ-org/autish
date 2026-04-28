# AGENTS-disko.md — disko Command Agent Instructions

## Summary
Storage device management CLI — list, mount, unmount, and check health of disks.

## Purpose and Expected Behavior
- List connected storage devices with details (`ls`).
- Check disk health via SMART (`sano`).
- Mount/unmount disks with optional mount point (`munti`, `malmunti`).
- Detect filesystem types and available space.

## Constraints and Invariants
- Depends on system tools: `lsblk`, `smartctl`, `mount`, `umount`.
- All subprocess calls wrapped via `_run_command()` helper with error handling.
- No persistent state; read-only queries and mount operations.
- Output via Rich `Table` and `Console`.

## Input/Output Expectations
- Subcommands: `ls`, `sano`, `munti`, `malmunti`
- CLI Options:
  - `ls`: `[nomo]` (device name filter)
  - `sano`: `<nomo>` (device name, required)
  - `munti`: `<nomo>` (device name, required), `-l`/`--loko` (mount point, default auto)
  - `malmunti`: `<nomo>` (device name, required)
- Output: Rich tables with device info, health status, mount status
- Side Effects: Mount/umount operations (requires privileges)

## Documentation Reference
- `docs/man/disko.md`

## Domain-Specific Rules for Agents
- Always use `_run_command()` wrapper; never bare `subprocess.run()`.
- `smartctl` may require sudo; handle permission errors gracefully with clear message.
- Device name format: e.g., `/dev/sda1`, `nvme0n1p1`; accept both full path and short name.
- Mount point auto-detection: use `/mnt/<device_name>` if `-l` not specified.
- Size formatting: use `_format_size()` helper (bytes → human-readable).
- Do not add GUI/TUI components; keep CLI-only per global rules.
